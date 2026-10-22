from datetime import date

from pipeline.prepare import Attachments
from pipeline.record import build_record, error_record
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
    assert meta["conflicts"] == ["bank: rules found Deutsche Bank, model said Barclays"]
    assert (meta["date_source"], meta["title_verified"]) == ("text+llm", True)
    assert (meta["model"], meta["prompt_version"]) == (MODEL, PROMPT)


def test_market_wrap_record_has_the_forced_values():
    record = build_record(
        prepared_email(), llm_output(market_wrap_checklist=checklist(yes=6)), MODEL, PROMPT
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
    assert (record.bank, record.date, record.source_file) == (
        "Deutsche Bank",
        date(2026, 4, 10),
        "035300",
    )
    assert (record.folder_name, record.market_wrap, record.asset_tags) == (None, None, [])
    assert record.meta.error == "Timeout: no reply within 300s"
