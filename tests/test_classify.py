import json

import pytest

import classify
from classify import RunStopped, classify_all, summary, write_deliverable, write_json
from pipeline.llm_cache import Cache
from pipeline.llm_client import CallResult, LLMError, Settings, StopRun
from pipeline.reviewed import Reviewed
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


def test_reviewed_answers_reach_only_their_email(tmp_path):
    reviewed = {"035301": [Reviewed("market_wrap", "YES", "a recap")]}
    quiet = lambda line: None  # noqa: E731
    outcomes = classify_all(
        emails(), SETTINGS, Cache(tmp_path), False, FakeClassifier(), quiet, reviewed=reviewed
    )
    assert [o.record.market_wrap for o in outcomes] == ["NO", "YES"]


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


BRIEF_FIELDS = [
    "folder_name",
    "bank",
    "date",
    "market_wrap",
    "primary_asset_tag",
    "asset_tags",
    "companies_mentioned",
    "industry_subindustry",
    "pdf_attachment",
    "source_file",
]


def test_deliverable_has_exactly_the_brief_fields_and_details_hold_the_rest(tmp_path):
    outcomes = run(Cache(tmp_path / "cache"), FakeClassifier())
    out, details = tmp_path / "classified_emails.json", tmp_path / "details.json"
    write_deliverable([o.record for o in reversed(outcomes)], out, details)
    records = json.loads(out.read_text())
    assert [list(r) for r in records] == [BRIEF_FIELDS, BRIEF_FIELDS]
    assert [r["source_file"] for r in records] == ["035300", "035301"]
    meta = json.loads(details.read_text())
    assert meta["035300"]["model"] == "ollama_chat/test"


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


def test_the_command_writes_the_run_folder_and_only_a_full_run_writes_the_deliverable(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/test-model")
    for email_id in ["035300", "035301"]:
        (tmp_path / "Data" / email_id).mkdir(parents=True)
        (tmp_path / "Data" / email_id / "emailbody.html").write_text(
            "<p>FX Daily 10 April 2026</p>"
        )
    fake = FakeClassifier()
    monkeypatch.setattr("classify.classify_email", fake)

    monkeypatch.setattr("sys.argv", ["classify.py", "--limit", "1"])
    classify.main()
    run = tmp_path / "output" / "runs" / "test-model_1-emails"
    assert sorted(p.name for p in run.iterdir()) == [
        "classified_emails.json",
        "classified_emails_details.json",
        "review.csv",
        "summary.txt",
    ]
    assert not (tmp_path / "classified_emails.json").exists()

    monkeypatch.setattr("sys.argv", ["classify.py"])
    classify.main()
    deliverable = json.loads((tmp_path / "classified_emails.json").read_text())
    assert len(deliverable) == 2
    assert list(deliverable[0]) == BRIEF_FIELDS
    details = json.loads((tmp_path / "classified_emails_details.json").read_text())
    assert sorted(details) == ["035300", "035301"]
    assert {"bank_llm", "bank_python", "flags"} <= set(details["035300"])
    assert (tmp_path / "output" / "runs" / "test-model" / "summary.txt").exists()

    # --force must ignore the cache: every email is sent again
    calls_before = len(fake.calls)
    monkeypatch.setattr("sys.argv", ["classify.py", "--force"])
    classify.main()
    assert len(fake.calls) == calls_before + 2


def test_a_correction_for_an_unknown_email_stops_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_MODEL", "ollama_chat/test-model")
    (tmp_path / "Data" / "035300").mkdir(parents=True)
    (tmp_path / "Data" / "035300" / "emailbody.html").write_text("<p>FX Daily</p>")
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "evaluation" / "reviewed.csv").write_text(
        "email,field,value,reason\n035399,market_wrap,YES,a recap\n"
    )
    fake = FakeClassifier()
    monkeypatch.setattr("classify.classify_email", fake)
    monkeypatch.setattr("sys.argv", ["classify.py", "--only", "035300"])

    assert classify.main() == 1
    assert "no email '035399' in the data" in capsys.readouterr().out
    assert fake.calls == []


def test_cloud_models_wait_between_calls_but_not_for_cached_answers(tmp_path):
    cloud = Settings("gemini/x", None, 32768, None, seconds_between_calls=6.5)
    # the clock is read when each call starts: first call at 0 s, second email ready at 2 s
    waits, now = [], iter([0.0, 2.0, 8.5])
    cache = Cache(tmp_path)
    quiet = lambda line: None  # noqa: E731
    classify_all(
        emails(), cloud, cache, False, FakeClassifier(), quiet, waits.append, lambda: next(now)
    )
    assert waits == [4.5]  # a 6.5 s gap, 2 s already passed
    classify_all(emails(), cloud, cache, False, FakeClassifier(), quiet, waits.append)
    assert waits == [4.5]  # all cached: no waiting


def test_a_stopped_run_keeps_what_was_finished(tmp_path):
    class QuotaAfterOne(FakeClassifier):
        def __call__(self, llm_input, settings):
            if self.calls:
                raise StopRun("daily free quota used up")
            return super().__call__(llm_input, settings)

    with pytest.raises(RunStopped, match="daily free quota") as stopped:
        classify_all(emails(), SETTINGS, Cache(tmp_path), False, QuotaAfterOne(), lambda line: None)
    assert [o.record.source_file for o in stopped.value.outcomes] == ["035300"]


def test_missing_api_key_stops_before_anything_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Data" / "035300").mkdir(parents=True)
    (tmp_path / "Data" / "035300" / "emailbody.html").write_text("<p>FX Daily</p>")
    monkeypatch.setenv("LLM_MODEL", "gemini-flash-lite")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr("sys.argv", ["classify.py"])
    assert classify.main() == 2
    assert "gemini-flash-lite needs GEMINI_API_KEY in .env" in capsys.readouterr().out
    assert not (tmp_path / "output").exists()
