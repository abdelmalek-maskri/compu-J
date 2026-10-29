import json
from types import SimpleNamespace

import litellm
import pytest

from pipeline.llm_client import CallResult, LLMError, Settings, StopRun, classify_email, complete
from tests.factories import llm_output_data

SETTINGS = Settings(model="ollama_chat/test", api_base=None, num_ctx=32768, reasoning_effort=None)
GOOD = json.dumps(llm_output_data())


def reply(content: str, prompt_tokens: int = 2000):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=250),
    )


class FakeModel:
    """plays back a script of replies or errors, and records what it was sent"""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, settings, messages):
        self.calls.append(messages)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def connection_error():
    return litellm.exceptions.APIConnectionError(
        message="refused", llm_provider="ollama", model="m"
    )


def run(fake, waits=None):
    waits = [] if waits is None else waits
    return classify_email("EMAIL BODY:\nFX Daily", SETTINGS, fake, waits.append)


def test_valid_answer_on_the_first_try():
    result = run(FakeModel(reply(GOOD)))
    assert isinstance(result, CallResult)
    assert (result.output.bank, result.attempts, result.prompt_tokens) == ("Deutsche Bank", 1, 2000)
    assert result.warnings == []


def test_invalid_answer_gets_one_retry_that_explains_the_problem():
    bad = json.dumps(llm_output_data(asset_tags=["Crypto"]))
    fake = FakeModel(reply(bad), reply(GOOD))

    result = run(fake)

    assert result.attempts == 2
    assert result.prompt_tokens == 4000
    retry_messages = fake.calls[1]
    assert retry_messages[2] == {"role": "assistant", "content": bad}
    assert "asset_tags" in retry_messages[3]["content"]


def test_invalid_twice_fails_this_email():
    with pytest.raises(LLMError, match="did not match the schema twice"):
        run(FakeModel(reply("not json"), reply("")))


def test_connection_errors_are_retried_with_growing_waits():
    waits = []
    result = run(FakeModel(connection_error(), connection_error(), reply(GOOD)), waits)
    assert result.attempts == 1
    assert waits == [5, 20]


def test_connection_keeps_failing():
    waits = []
    with pytest.raises(LLMError, match="APIConnectionError after 3 tries"):
        run(FakeModel(connection_error(), connection_error(), connection_error()), waits)
    assert waits == [5, 20]


def test_bad_request_is_not_retried():
    too_long = litellm.exceptions.ContextWindowExceededError(
        message="too long", model="m", llm_provider="ollama"
    )
    fake = FakeModel(too_long)
    with pytest.raises(LLMError, match="ContextWindowExceededError"):
        run(fake)
    assert len(fake.calls) == 1


def test_missing_model_or_bad_key_stops_the_whole_run():
    missing = litellm.exceptions.NotFoundError(message="pull it", model="m", llm_provider="ollama")
    with pytest.raises(StopRun, match="NotFoundError"):
        run(FakeModel(missing))
    bad_key = litellm.exceptions.AuthenticationError(
        message="invalid key", llm_provider="gemini", model="m"
    )
    with pytest.raises(StopRun, match="AuthenticationError"):
        run(FakeModel(bad_key))


def rate_limited():
    return litellm.exceptions.RateLimitError(message="429", llm_provider="gemini", model="m")


def test_rate_limit_waits_longer_then_succeeds():
    waits = []
    result = run(FakeModel(rate_limited(), reply(GOOD)), waits)
    assert (result.attempts, waits) == (1, [30])


def test_rate_limit_that_never_ends_stops_the_run():
    waits = []
    with pytest.raises(StopRun, match="daily free quota"):
        run(FakeModel(*[rate_limited()] * 4), waits)
    assert waits == [30, 60, 120]


def test_presets_carry_their_settings(monkeypatch):
    gemini = Settings.from_name("gemini-flash-lite")
    assert (gemini.model, gemini.name, gemini.is_ollama) == (
        "gemini/gemini-3.5-flash-lite",
        "gemini-flash-lite",
        False,
    )
    assert (gemini.seconds_between_calls, gemini.api_key_env) == (6.5, "GEMINI_API_KEY")
    gemma = Settings.from_name("gemma")
    assert (gemma.reasoning_effort, gemma.is_ollama, gemma.name) == ("none", True, "gemma")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini.missing_key() == "GEMINI_API_KEY"
    monkeypatch.setenv("GEMINI_API_KEY", "set")
    assert gemini.missing_key() is None


def test_ollama_only_settings_are_not_sent_to_cloud_models(monkeypatch):
    sent = []
    monkeypatch.setattr("litellm.completion", lambda **options: sent.append(options))
    complete(Settings.from_name("gemma"), [])
    complete(Settings.from_name("gemini-flash-lite"), [])
    ollama, gemini = sent
    assert (ollama["num_ctx"], ollama["reasoning_effort"], ollama["temperature"]) == (
        32768,
        "none",
        0,
    )
    assert not {"num_ctx", "api_base", "reasoning_effort", "temperature"} & set(gemini)


def test_context_warning_is_only_for_ollama():
    cloud = Settings("gemini/gemini-3.5-flash-lite", None, 32768, None)
    result = classify_email("x", cloud, FakeModel(reply(GOOD, prompt_tokens=31500)), [].append)
    assert result.warnings == []


def test_input_near_the_context_limit_is_flagged():
    result = run(FakeModel(reply(GOOD, prompt_tokens=31500)))
    assert result.warnings == ["input used 31500 of 32768 tokens, it may have been cut off"]


def test_the_default_model_is_the_one_used_for_the_results(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = Settings.from_env()
    assert (settings.preset, settings.api_key_env) == ("gemini-flash-lite", "GEMINI_API_KEY")


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/gpt-oss:20b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    assert Settings.from_env() == Settings(
        "ollama_chat/gpt-oss:20b", "http://localhost:11434", 16384, "low"
    )
