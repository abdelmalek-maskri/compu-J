"""smoke test: the model answers, returns schema valid JSON and reads long input whole

run from the repo root: uv run python -m scripts.smoke_test_llm [--model gemini-flash-lite]
it sends two requests to the model, so it uses two of a free cloud tier's daily requests
"""

import argparse
import sys
import time
from typing import Literal

import litellm
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from pipeline.llm_client import Settings, complete


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


def call(settings: Settings, text: str) -> tuple[Probe, int, float]:
    messages = [
        {"role": "system", "content": "Classify the research note. Reply with JSON only."},
        {"role": "user", "content": text},
    ]
    start = time.perf_counter()
    # the same call classify.py makes, so this checks the real settings for this model
    try:
        resp = complete(settings, messages, Probe)
    except litellm.exceptions.NotFoundError as e:
        raise CheckFailed(f"model not found: pull it in Ollama or fix the model name ({e})") from e
    except litellm.exceptions.AuthenticationError as e:
        raise CheckFailed(f"the API key was refused, check {settings.api_key_env} ({e})") from e
    except litellm.exceptions.RateLimitError as e:
        raise CheckFailed(f"rate limit or daily quota reached, try later ({e})") from e
    except litellm.exceptions.Timeout as e:
        raise CheckFailed(f"no reply within 300s, a first local load can be slow ({e})") from e
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="a preset name or model string; default LLM_MODEL in .env")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings.from_name(args.model) if args.model else Settings.from_env()
    print(f"model: {settings.name} ({settings.model})")
    if missing := settings.missing_key():
        print(f"FAILED: {settings.name} needs {missing} in .env")
        return 1

    try:
        probe, tokens, seconds = call(settings, SAMPLE)
        print(f"[1/2] schema: ok in {seconds:.1f}s, {tokens} prompt tokens\n      {probe}")

        time.sleep(settings.seconds_between_calls)
        probe, tokens, seconds = call(settings, FILLER + "\n\n" + SAMPLE)
        if tokens < MIN_LONG_PROMPT_TOKENS:
            raise CheckFailed(
                f"long input was cut to {tokens} tokens: for Ollama, num_ctx is not arriving"
            )
        print(f"[2/2] long input: ok in {seconds:.1f}s, {tokens} prompt tokens read")
    except CheckFailed as e:
        print(f"FAILED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
