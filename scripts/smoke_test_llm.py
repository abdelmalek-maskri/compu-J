"""smoke test: the model answers, returns schema valid JSON and reads long input whole"""

import os
import sys
import time
from typing import Literal

import litellm
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


class Probe(BaseModel):
    bank: str
    asset_class: Literal[
        "Macro", "Fixed Income", "Equity", "Commodities", "FX", "Thematics", "Market Wrap"
    ]
    is_market_wrap: bool


class CheckFailed(Exception):
    pass


SAMPLE = (
    "Deutsche Bank Research, 10 April 2026. FX Daily: the dollar weakened against the yen "
    "after softer US CPI. We stay short USD/JPY with a target of 140."
)

# about 12k tokens: longer than Ollama's default window, shorter than OLLAMA_NUM_CTX
FILLER = "Analysts reviewed sector earnings, rates and currency moves across regions. " * 1000
MIN_LONG_PROMPT_TOKENS = 10_000


def call(model: str, text: str) -> tuple[Probe, int, float]:
    start = time.perf_counter()
    try:
        resp = litellm.completion(
            model=model,
            api_base=os.getenv("OLLAMA_API_BASE") if model.startswith("ollama") else None,
            messages=[
                {"role": "system", "content": "Classify the research note. Reply with JSON only."},
                {"role": "user", "content": text},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "probe", "schema": Probe.model_json_schema()},
            },
            num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
            # litellm maps "none" to ollama's think=false; gpt-oss only accepts low/medium/high
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or None,
            # the model's own default is 1.0; classification should be repeatable
            temperature=0,
            timeout=300,
        )
    except litellm.exceptions.NotFoundError as e:
        raise CheckFailed(f"model not found, run `ollama pull` or fix LLM_MODEL ({e})") from e
    except litellm.exceptions.Timeout as e:
        raise CheckFailed(f"no reply within 300s, first load can be slow, retry ({e})") from e
    except litellm.exceptions.APIConnectionError as e:
        raise CheckFailed(f"could not reach the model, is Ollama running? ({e})") from e
    seconds = time.perf_counter() - start

    raw = resp.choices[0].message.content
    if not raw:
        raise CheckFailed("model replied with empty content")
    try:
        probe = Probe.model_validate_json(raw)
    except ValidationError as e:
        raise CheckFailed(f"reply does not match the schema\nraw: {raw}\n{e}") from e
    return probe, resp.usage.prompt_tokens, seconds


def main() -> int:
    load_dotenv()
    model = os.getenv("LLM_MODEL", "ollama_chat/gemma4:26b-a4b-it-qat")
    print(f"model: {model}")

    try:
        probe, tokens, seconds = call(model, SAMPLE)
        print(f"[1/2] schema: ok in {seconds:.1f}s, {tokens} prompt tokens\n      {probe}")

        probe, tokens, seconds = call(model, FILLER + "\n\n" + SAMPLE)
        if tokens < MIN_LONG_PROMPT_TOKENS:
            raise CheckFailed(
                f"long input was truncated to {tokens} tokens, num_ctx is not reaching the model"
            )
        print(f"[2/2] long input: ok in {seconds:.1f}s, {tokens} prompt tokens read")
    except CheckFailed as e:
        print(f"FAILED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
