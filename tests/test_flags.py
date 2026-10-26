import csv
from datetime import date

from pipeline.build_record import build_record
from pipeline.check_metadata import check_metadata
from pipeline.flags import logic_flags, metadata_flags, review_rows, write_review
from tests.factories import checklist, llm_output, prepared_email

UBP_FLYER = (
    "Structured Product Investment Proposal\n15 months tenor in USD, issued by Goldman Sachs\n"
    "Best regards, Union Bancaire Privee, UBP SA"
)


def fields(flags):
    return [(f.kind, f.field) for f in flags]


def test_a_consistent_answer_raises_no_flags():
    # keeping flags rare is what makes the review file worth reading
    email, output = prepared_email(), llm_output()
    assert metadata_flags(check_metadata(email, output)) == []
    assert logic_flags(output) == []


def test_bank_disagreement_says_which_answer_was_kept():
    email = prepared_email(
        body=UBP_FLYER, bank="Goldman Sachs", bank_source="top_text", date=None, date_source=None
    )
    title = "Structured Product Investment Proposal"
    output = llm_output(bank="UBP", date=None, date_quote=None, title=title)
    [flag] = metadata_flags(check_metadata(email, output))
    assert (flag.field, flag.value_a, flag.value_b) == ("bank", "UBP", "Goldman Sachs")
    assert flag.note.endswith("Kept the AI's answer, because the email names that bank.")


def test_model_bank_missing_from_the_email_is_flagged():
    [flag] = metadata_flags(check_metadata(prepared_email(), llm_output(bank="Barclays")))
    assert (
        flag.note == "The AI says Barclays; the rules say Deutsche Bank. Kept the rules' answer, "
        "because the AI's bank is not named in the email."
    )


def test_filling_a_gap_or_being_unsure_is_not_a_disagreement():
    email = prepared_email(bank=None, bank_source=None, body="Banque Pictet Daily\n10 April 2026")
    output = llm_output(bank="Pictet", title="Banque Pictet Daily")
    assert metadata_flags(check_metadata(email, output)) == []
    assert metadata_flags(check_metadata(prepared_email(), llm_output(bank="Other"))) == []


def test_rejected_model_date_is_flagged_with_its_quote():
    output = llm_output(date="2026-04-17", date_quote="17.04.2026")
    [flag] = metadata_flags(check_metadata(prepared_email(), output))
    assert (flag.field, flag.value_a, flag.value_b) == ("date", "2026-04-17", "2026-04-10")
    assert "quoting '17.04.2026', but that could not be confirmed" in flag.note


def test_model_finding_no_date_while_the_rules_did_is_flagged():
    # 035274: the rules took "report as of 31.03.2026", the model rightly found no date
    [flag] = metadata_flags(
        check_metadata(prepared_email(), llm_output(date=None, date_quote=None))
    )
    assert (flag.field, flag.value_a, flag.value_b) == ("date", None, "2026-04-10")
    assert flag.note.startswith(
        "The AI found no publication date; the rules found 10 April 2026 in the email's text."
    )


def test_title_not_in_the_email_is_flagged():
    flags = metadata_flags(check_metadata(prepared_email(), llm_output(title="Weekly FX Outlook")))
    assert fields(flags) == [("model_vs_python", "title")]


def test_wrap_with_an_analytical_purpose_is_flagged():
    # gemma on Goldman's "Macro at a Glance": 6 of 7 checks, but purpose said no
    checks = checklist(yes=7) | {"purpose": False}
    flags = logic_flags(llm_output(market_wrap="YES", market_wrap_checklist=checks))
    assert [(f.value_b, f.field) for f in flags] == [("purpose: no", "market_wrap")]


def test_decision_against_its_own_checklist_is_flagged():
    against = logic_flags(
        llm_output(
            market_wrap="YES",
            market_wrap_checklist=checklist(yes=4) | {"structure": False, "asset_coverage": False},
        )
    )
    assert any(f.value_b == "2/7 checks" for f in against)
    assert logic_flags(llm_output(market_wrap="NO", market_wrap_checklist=checklist(yes=6)))[
        0
    ].note.startswith("The AI decided this is not a market wrap")


def test_market_wrap_as_main_class_while_deciding_no_is_flagged():
    # 035437: "Market Wrap" as primary tag, decision NO, nothing else, so no class was left
    [flag] = logic_flags(llm_output(primary_asset_tag="Market Wrap", asset_tags=["Market Wrap"]))
    assert (flag.field, flag.value_a, flag.value_b) == (
        "primary_asset_tag",
        "Market Wrap",
        "decision: NO",
    )
    assert flag.note.endswith("leaving no main asset class.")
    [flag] = logic_flags(llm_output(primary_asset_tag="Market Wrap", asset_tags=["FX"]))
    assert not flag.note.endswith("leaving no main asset class.")


def test_event_called_a_wrap_is_flagged():
    output = llm_output(market_wrap="YES", content_type="event", market_wrap_checklist=checklist(7))
    assert [f.value_b for f in logic_flags(output)] == ["content type: event"]


def test_companies_without_an_equity_tag_are_flagged():
    # both models on the Barclays MedTech trip: Thematics, with 24 companies listed
    output = llm_output(
        primary_asset_tag="Thematics",
        asset_tags=["Thematics"],
        companies_mentioned=["Sartorius", "Coloplast"],
    )
    [flag] = logic_flags(output)
    assert (flag.field, flag.value_a) == ("companies_mentioned", "2 companies")


def test_half_a_date_answer_is_flagged():
    assert fields(logic_flags(llm_output(date="2026-04-10", date_quote=None))) == [
        ("model_logic", "date")
    ]
    assert fields(logic_flags(llm_output(date=None, date_quote="10 April 2026"))) == [
        ("model_logic", "date")
    ]


def test_an_inferred_date_is_kept_apart_and_flagged_for_a_person():
    email = prepared_email(date=None, date_source=None, date_hint=date(2026, 4, 13))
    record = build_record(email, llm_output(date=None, date_quote=None), "model", "v2")
    assert (record.date, record.meta.date_hint) == (None, date(2026, 4, 13))
    assert [(f.kind, f.field, f.value_a) for f in record.meta.flags] == [
        ("inferred", "date", "2026-04-13")
    ]


def test_no_hint_when_the_email_states_a_date():
    email = prepared_email(date_hint=date(2026, 4, 13))
    record = build_record(email, llm_output(), "model", "v2")
    assert (record.date, record.meta.date_hint) == (date(2026, 4, 10), None)
    assert all(f.kind != "inferred" for f in record.meta.flags)


def test_review_file_has_one_row_per_flag_and_an_empty_verdict(tmp_path):
    record = build_record(
        prepared_email(), llm_output(bank="Barclays", title="Weekly FX Outlook"), "model", "v2"
    )
    path = tmp_path / "classified.review.csv"
    write_review(review_rows([record], "gemma"), path)
    rows = list(csv.DictReader(path.open()))
    assert [(r["email"], r["model"], r["field"], r["your_verdict"]) for r in rows] == [
        ("035300", "gemma", "bank", ""),
        ("035300", "gemma", "title", ""),
    ]
    assert record.meta.received is None or isinstance(record.meta.received, date)
