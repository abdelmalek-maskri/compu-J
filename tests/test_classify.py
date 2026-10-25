import json

from classify import classify_all, summary, write_json
from pipeline.llm_cache import Cache
from pipeline.llm_client import CallResult, LLMError, Settings
from tests.factories import llm_output, prepared_email

SETTINGS = Settings(model="ollama_chat/test", api_base=None, num_ctx=32768, reasoning_effort=None)


class FakeClassifier:
    def __init__(self, fail_for=()):
        self.fail_for, self.calls = set(fail_for), []

    def __call__(self, llm_input, settings):
        self.calls.append(llm_input)
        if any(marker in llm_input for marker in self.fail_for):
            raise LLMError("Timeout after 3 tries")
        return CallResult(
            output=llm_output(),
            prompt_tokens=2600,
            output_tokens=280,
            seconds=20.0,
            attempts=1,
            warnings=["input used 31500 of 32768 tokens, it may have been cut off"],
        )


def emails():
    return [
        prepared_email(id="035300", body="FX Daily: USD/JPY\n10 April 2026"),
        prepared_email(id="035301", body="FX Weekly: EUR\n10 April 2026"),
    ]


def run(cache, fake, force=False):
    return classify_all(emails(), SETTINGS, cache, force, fake, log=lambda line: None)


def test_every_email_gets_a_record_and_answers_are_cached(tmp_path):
    cache, fake = Cache(tmp_path), FakeClassifier()
    first = run(cache, fake)
    assert [o.record.source_file for o in first] == ["035300", "035301"]
    assert [o.cached for o in first] == [False, False]

    second = run(cache, fake)
    assert [o.cached for o in second] == [True, True]
    assert len(fake.calls) == 2  # nothing was sent again


def test_force_ignores_the_cache(tmp_path):
    cache, fake = Cache(tmp_path), FakeClassifier()
    run(cache, fake)
    run(cache, fake, force=True)
    assert len(fake.calls) == 4


def test_a_failed_email_still_gets_a_record_and_is_retried_next_time(tmp_path):
    cache = Cache(tmp_path)
    outcomes = run(cache, FakeClassifier(fail_for=["FX Weekly"]))
    failed = outcomes[1].record
    assert failed.meta.error == "Timeout after 3 tries"
    assert (failed.bank, failed.market_wrap) == ("Deutsche Bank", None)

    retry = FakeClassifier()
    run(cache, retry)
    assert retry.calls == [emails()[1].llm_input]


def test_call_warnings_reach_the_record(tmp_path):
    outcomes = run(Cache(tmp_path), FakeClassifier())
    assert outcomes[0].record.meta.warnings == [
        "input used 31500 of 32768 tokens, it may have been cut off"
    ]


def test_output_is_sorted_and_written_whole(tmp_path):
    outcomes = run(Cache(tmp_path / "cache"), FakeClassifier())
    out = tmp_path / "classified_emails.json"
    write_json([o.record for o in reversed(outcomes)], out)
    data = json.loads(out.read_text())
    assert [d["source_file"] for d in data] == ["035300", "035301"]
    assert list(data[0])[:3] == ["folder_name", "bank", "date"]
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_summary_reports_failures_and_timing(tmp_path):
    outcomes = run(Cache(tmp_path), FakeClassifier(fail_for=["FX Weekly"]))
    text = summary(outcomes, SETTINGS)
    assert text.startswith("1 classified, 1 failed ['035301']")
    assert "average 20s" in text
