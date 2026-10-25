import csv
import sys

from pipeline.build_record import build_record
from pipeline.flags import model_vs_model_flags
from pipeline.llm_client import CallResult
from scripts import compare_models
from scripts.compare_models import spread_sample
from tests.factories import checklist, llm_output, prepared_email


def test_spread_sample_reaches_across_the_whole_dataset():
    emails = [prepared_email(id=f"{i:06}") for i in range(200)]
    picked = [e.id for e in spread_sample(emails, 5)]
    assert picked == ["000000", "000050", "000100", "000149", "000199"]
    assert spread_sample(emails, 5) == spread_sample(emails, 5)
    assert len(spread_sample(emails, 500)) == 200
    assert [e.id for e in spread_sample(emails, 1)] == ["000000"]


def record(**answer):
    return build_record(prepared_email(), llm_output(**answer), "model", "v2")


def test_same_answers_raise_no_model_vs_model_flags():
    assert model_vs_model_flags(record(), record(), "gemma", "gemini-flash-lite") == []


def test_titles_and_companies_are_compared_ignoring_case_and_spacing():
    a = record(title="FX Daily: USD/JPY", primary_asset_tag="Equity", companies_mentioned=["Sony"])
    b = record(title="fx daily:  usd/jpy", primary_asset_tag="Equity", companies_mentioned=["SONY"])
    assert model_vs_model_flags(a, b, "a", "b") == []


def test_each_differing_field_is_flagged_with_both_answers():
    wrap = record(market_wrap="YES", market_wrap_checklist=checklist(yes=7))
    flags = model_vs_model_flags(record(), wrap, "gemma", "gemini-flash-lite")
    by_field = {f.field: (f.value_a, f.value_b) for f in flags}
    assert by_field["market_wrap"] == ("NO", "YES")
    assert by_field["primary_asset_tag"] == ("FX", "Market Wrap")
    assert {f.note for f in flags} == {"gemma vs gemini-flash-lite"}


def test_the_command_compares_two_models_and_writes_one_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for email_id in ["035300", "035301", "035302"]:
        (tmp_path / "Data" / email_id).mkdir(parents=True)
        (tmp_path / "Data" / email_id / "emailbody.html").write_text(
            "<img alt='Deutsche Bank Logo'><p>FX Daily: USD/JPY</p><p>10 April 2026</p>"
        )
    calls = []

    def fake_model(llm_input, settings):
        calls.append(settings.name)
        wrap = "YES" if settings.name == "model-b" else "NO"
        return CallResult(llm_output(market_wrap=wrap), 2000, 250, 1.0, 1)

    monkeypatch.setattr("classify.classify_email", fake_model)
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_models.py",
            "--models",
            "ollama_chat/model-a",
            "ollama_chat/model-b",
            "--emails",
            "2",
        ],
    )
    assert compare_models.main() == 0
    out = tmp_path / "output" / "comparisons" / "model-a_vs_model-b_2-emails"
    assert sorted(p.name for p in out.iterdir()) == [
        "agreement.txt",
        "model-a.json",
        "model-b.json",
        "review.csv",
    ]
    rows = list(csv.DictReader((out / "review.csv").open()))
    assert {
        (r["email"], r["model"], r["field"]) for r in rows if r["kind"] == "model_vs_model"
    } >= {
        ("035300", "model-a vs model-b", "market_wrap"),
        ("035302", "model-a vs model-b", "market_wrap"),
    }
    assert "market_wrap" in (out / "agreement.txt").read_text()

    # --no-run reuses the cache and never calls a model
    calls.clear()
    monkeypatch.setattr("sys.argv", [*sys.argv, "--no-run"])
    assert compare_models.main() == 0
    assert calls == []
