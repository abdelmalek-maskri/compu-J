"""one classification call to the configured model, local or cloud, with retries and checks"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm
from pydantic import BaseModel, ValidationError

from pipeline.model_presets import PRESETS
from pipeline.paths import model_slug
from pipeline.prompt import system_prompt
from pipeline.schema import LLMOutput

# temporary problems worth waiting for; anything else fails at once
RETRYABLE = (
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
)
RETRY_WAITS = (5, 20)
# a rate limit that outlasts these waits is a daily quota, which no amount of waiting fixes
RATE_LIMIT_WAITS = (30, 60, 120)
# problems that would hit every email the same way
STOPS_THE_RUN = (
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.PermissionDeniedError,
    litellm.exceptions.NotFoundError,
)
# Ollama truncates silently past num_ctx, so an input this close to it is flagged
CONTEXT_WARNING_SHARE = 0.95


class LLMError(Exception):
    """this email could not be classified; the run carries on with the next one"""


class StopRun(Exception):
    """no email can be classified now: wrong key, missing model or quota used up.
    answers already received are cached, so the next run carries on from here"""


@dataclass(frozen=True)
class Settings:
    model: str
    api_base: str | None
    num_ctx: int
    reasoning_effort: str | None
    timeout: int = 300
    preset: str | None = None
    seconds_between_calls: float = 0
    api_key_env: str | None = None

    @property
    def name(self) -> str:
        """used for folder names under output/"""
        return self.preset or model_slug(self.model)

    @property
    def is_ollama(self) -> bool:
        return self.model.startswith("ollama")

    def missing_key(self) -> str | None:
        """the environment variable this model needs but does not have"""
        if self.api_key_env and not os.getenv(self.api_key_env):
            return self.api_key_env
        return None

    @classmethod
    def from_name(cls, name: str) -> "Settings":
        """a preset name (see model_presets.py) or a full LiteLLM model string"""
        preset = PRESETS.get(name)
        model = preset.model if preset else name
        return cls(
            model=model,
            api_base=os.getenv("OLLAMA_API_BASE") if model.startswith("ollama") else None,
            num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
            reasoning_effort=preset.reasoning_effort
            if preset
            else os.getenv("LLM_REASONING_EFFORT") or None,
            preset=name if preset else None,
            seconds_between_calls=preset.seconds_between_calls if preset else 0,
            api_key_env=preset.api_key_env if preset else None,
        )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls.from_name(os.getenv("LLM_MODEL", "gemma"))


@dataclass
class CallResult:
    output: LLMOutput
    prompt_tokens: int
    output_tokens: int
    seconds: float
    attempts: int
    warnings: list[str] = field(default_factory=list)


def complete(settings: Settings, messages: list[dict], schema: type[BaseModel] = LLMOutput):
    """the only place that talks to a model; tests pass a fake instead"""
    options = {}
    if settings.is_ollama:
        # cloud models read far more than this; for Ollama it must be set or input is cut off
        options = {"api_base": settings.api_base, "num_ctx": settings.num_ctx}
    if settings.reasoning_effort:
        options["reasoning_effort"] = settings.reasoning_effort
    return litellm.completion(
        model=settings.model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema.__name__.lower(), "schema": schema.model_json_schema()},
        },
        temperature=0,
        timeout=settings.timeout,
        **options,
    )


def _complete_with_retries(complete_fn, settings, messages, sleep):
    waits, rate_waits = list(RETRY_WAITS), list(RATE_LIMIT_WAITS)
    while True:
        try:
            return complete_fn(settings, messages)
        except RETRYABLE as e:
            if not waits:
                tries = len(RETRY_WAITS) + 1
                raise LLMError(f"{type(e).__name__} after {tries} tries: {e}") from e
            sleep(waits.pop(0))
        except litellm.exceptions.RateLimitError as e:
            if not rate_waits:
                raise StopRun(
                    f"{settings.model} keeps refusing with a rate limit: the daily free quota is "
                    "probably used up. Run again later; answers so far are cached."
                ) from e
            sleep(rate_waits.pop(0))
        except STOPS_THE_RUN as e:
            raise StopRun(f"{type(e).__name__} from {settings.model}: {e}") from e
        except litellm.exceptions.BadRequestError as e:
            # includes an input too long for the model; retrying cannot help
            raise LLMError(f"{type(e).__name__}: {e}") from e


def classify_email(
    llm_input: str,
    settings: Settings,
    complete_fn: Callable = complete,
    sleep: Callable[[float], None] = time.sleep,
) -> CallResult:
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": llm_input},
    ]
    start = time.perf_counter()
    prompt_tokens = output_tokens = 0
    for attempt in (1, 2):
        response = _complete_with_retries(complete_fn, settings, messages, sleep)
        raw = response.choices[0].message.content or ""
        prompt_tokens += response.usage.prompt_tokens
        output_tokens += response.usage.completion_tokens

        warnings = []
        if (
            settings.is_ollama
            and response.usage.prompt_tokens >= settings.num_ctx * CONTEXT_WARNING_SHARE
        ):
            warnings.append(
                f"input used {response.usage.prompt_tokens} of {settings.num_ctx} tokens, "
                "it may have been cut off"
            )
        try:
            output = LLMOutput.model_validate_json(raw)
        except ValidationError as e:
            first = e.errors()[0]
            problem = f"{'.'.join(map(str, first['loc'])) or 'answer'}: {first['msg']}"
            if attempt == 2:
                raise LLMError(
                    f"answer did not match the schema twice, last problem {problem}"
                ) from e
            # one retry that tells the model what was wrong
            messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": f"That answer did not match the schema ({problem}). "
                    "Reply again with the corrected JSON only.",
                },
            ]
            continue
        return CallResult(
            output=output,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            seconds=time.perf_counter() - start,
            attempts=attempt,
            warnings=warnings,
        )
    raise AssertionError("unreachable: the loop returns or raises")
