from datetime import date

from pipeline.build_record import build_record, error_record
from pipeline.clean_emails import Attachments
from pipeline.repair_text import EN_DASH, R
from tests.factories import checklist, llm_output, prepared_email

MODEL, PROMPT = "ollama_chat/gemma4:26b-a4b-it-qat", "v1"


def test_record_combines_rules_metadata_and_files():
    email = prepared_email(attachments=Attachments(["FXView.pdf"], [], {}))
    output = llm_output(asset_tags=["JPY"], bank="Barclays")

    record = build_record(email, output, MODEL, PROMPT).model_dump(mode="json")

    assert record["folder_name"] == "FX Daily: USD/JPY"
    assert (record["bank"], record["date"]) == ("Deutsche Bank", "2026-04-10")
    assert (record["market_wrap"], record["primary_asset_tag"]) == ("NO", "FX")
    assert record["asset_tags"] == ["FX", "JPY"]
    assert record["pdf_attachment"] == ["FXView.pdf"]
    assert record["source_file"] == "035300"
    meta = record["meta"]
    assert [(f["kind"], f["field"]) for f in meta["flags"]] == [("model_vs_python", "bank")]
    assert (meta["bank_llm"], meta["bank_python"]) == ("Barclays", "Deutsche Bank")
    assert (meta["date_source"], meta["title_verified"]) == ("llm+python", True)
    assert (meta["model"], meta["prompt_version"]) == (MODEL, PROMPT)


def test_market_wrap_record_has_the_forced_values():
    record = build_record(
        prepared_email(),
        llm_output(market_wrap="YES", market_wrap_checklist=checklist(yes=6)),
        MODEL,
        PROMPT,
    )
    assert record.market_wrap == "YES"
    assert record.asset_tags == ["Market Wrap"]
    assert (record.companies_mentioned, record.industry_subindustry) == ([], [])


def test_corrections_and_duplicates_reach_meta():
    email = prepared_email(duplicate_of="035427")
    output = llm_output(primary_asset_tag="Fixed Income", asset_tags=["Credit Strategy"])
    meta = build_record(email, output, MODEL, PROMPT).meta
    assert meta.duplicate_of == "035427"
    assert meta.corrections == []  # the parent was the primary tag, so nothing was added

    output = llm_output(primary_asset_tag="Macro", asset_tags=["Credit Strategy"])
    assert build_record(email, output, MODEL, PROMPT).meta.corrections == [
        "added parent Fixed Income for Credit Strategy"
    ]


def test_no_pdfs_means_null_attachment():
    assert build_record(prepared_email(), llm_output(), MODEL, PROMPT).pdf_attachment is None


def test_failed_call_keeps_what_python_found():
    email = prepared_email(received=date(2026, 4, 10))
    record = error_record(email, "Timeout: no reply within 300s", MODEL, PROMPT)
    # the rules' date is kept for review but never published on its own
    assert (record.bank, record.date, record.source_file) == ("Deutsche Bank", None, "035300")
    assert record.meta.date_python == date(2026, 4, 10)
    assert (record.folder_name, record.market_wrap, record.asset_tags) == (None, None, [])
    assert record.meta.error == "Timeout: no reply within 300s"


def test_failed_call_uses_a_link_date_only_as_not_confirmed():
    email = prepared_email(date_hint=date(2026, 4, 13))
    record = error_record(email, "Timeout: no reply within 300s", MODEL, PROMPT)
    assert (record.date, record.meta.date_source) == (date(2026, 4, 13), "link")
    assert [f.kind for f in record.meta.flags] == ["inferred"]


def test_the_title_is_repaired_after_it_is_checked_against_the_email():
    title = f"Mexico {R} Short-term outlook"
    email = prepared_email(body=f"{title}\n10 April 2026")

    record = build_record(email, llm_output(title=title), MODEL, PROMPT)

    assert record.folder_name == f"Mexico {EN_DASH} Short-term outlook"
    assert record.meta.title_verified
