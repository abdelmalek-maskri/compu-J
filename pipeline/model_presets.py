"""the models this project has been tried with, each with the settings it needs

use a preset name anywhere a model is asked for (LLM_MODEL in .env, --models in scripts).
a full LiteLLM model string also works, with LLM_REASONING_EFFORT read from .env
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    model: str
    reasoning_effort: str | None = None
    # free cloud tiers limit requests per minute; waiting this long between calls stays under it
    seconds_between_calls: float = 0
    api_key_env: str | None = None
    # 0 makes local models answer the same way every time (their default is 1). Gemini 3 is
    # phasing the setting out, so it gets none; the cache keeps its answers repeatable
    temperature: float | None = 0


PRESETS = {
    # local through Ollama: free, private, slow; gemma's thinking off, gpt-oss cannot turn it off
    "gemma": Preset("ollama_chat/gemma4:26b-a4b-it-qat", reasoning_effort="none"),
    "gpt-oss-20b": Preset("ollama_chat/gpt-oss:20b", reasoning_effort="low"),
    # Gemini free tier, about 10 requests a minute and 500 a day: enough for all 200 emails.
    # check the limits of your own project in Google AI Studio
    "gemini-flash-lite": Preset(
        "gemini/gemini-3.5-flash-lite",
        seconds_between_calls=6.5,
        api_key_env="GEMINI_API_KEY",
        temperature=None,
    ),
    # stronger, but about 5 a minute and only 20 a day: small comparisons only
    "gemini-flash": Preset(
        "gemini/gemini-3.8-flash",
        seconds_between_calls=12.5,
        api_key_env="GEMINI_API_KEY",
        temperature=None,
    ),
}
