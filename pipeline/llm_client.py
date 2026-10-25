"""one classification call to the configured model, with retries and checks"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import litellm
from pydantic import ValidationError

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
# Ollama truncates silently past num_ctx, so an input this close to it is flagged
CONTEXT_WARNING_SHARE = 0.95


class LLMError(Exception):
    """this email could not be classified; the run carries on with the next one"""


@dataclass(frozen=True)
class Settings:
    model: str
    api_base: str | None
    num_ctx: int
    reasoning_effort: str | None
    timeout: int = 300

    @property
    def name(self) -> str:
        """used for folder names under output/"""
        return model_slug(self.model)

    @classmethod
    def from_env(cls) -> "Settings":
        model = os.getenv("LLM_MODEL", "ollama_chat/gemma4:26b-a4b-it-qat")
        return cls(
            model=model,
            api_base=os.getenv("OLLAMA_API_BASE") if model.startswith("ollama") else None,
            num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or None,
        )


@dataclass
class CallResult:
    output: LLMOutput
    prompt_tokens: int
    output_tokens: int
    seconds: float
    attempts: int
    warnings: list[str] = field(default_factory=list)


def complete(settings: Settings, messages: list[dict]):
    """the only place that talks to the model; tests pass a fake instead"""
    return litellm.completion(
        model=settings.model,
        api_base=settings.api_base,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "classification", "schema": LLMOutput.model_json_schema()},
        },
        num_ctx=settings.num_ctx,
        reasoning_effort=settings.reasoning_effort,
        temperature=0,
        timeout=settings.timeout,
    )


def _complete_with_retries(complete_fn, settings, messages, sleep):
    for wait in (*RETRY_WAITS, None):
        try:
            return complete_fn(settings, messages)
        except RETRYABLE as e:
            if wait is None:
                tries = len(RETRY_WAITS) + 1
                raise LLMError(f"{type(e).__name__} after {tries} tries: {e}") from e
            sleep(wait)
        except litellm.exceptions.BadRequestError as e:
            # includes an input too long for the model; retrying cannot help
            raise LLMError(f"{type(e).__name__}: {e}") from e


def classify_email(
    llm_input: str,
    settings: Settings,
    complete_fn: Callable = complete,
    sleep: Callable[[float], None] = time.sleep,
) -> CallResult:
    """NotFoundError (model not pulled) is not caught: every other email would fail the same way"""
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
        if response.usage.prompt_tokens >= settings.num_ctx * CONTEXT_WARNING_SHARE:
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
