from datetime import date

import pytest
from pydantic import ValidationError

from pipeline.schema import ClassifiedEmail, LLMOutput, Meta

CHECKLIST = {
    "structure": False,
    "asset_coverage": False,
    "timeframe": False,
    "purpose": False,
    "title": False,
    "language": False,
    "depth": False,
}


def llm_output(**overrides):
    data = {
        "title": "FX Daily: USD/JPY",
        "bank": "Deutsche Bank",
        "date": "2026-04-10",
        "date_quote": "10 April 2026",
        "content_type": "research",
        "market_wrap_checklist": CHECKLIST,
        "primary_asset_tag": "FX",
        "asset_tags": ["FX", "JPY"],
        "companies_mentioned": [],
        "industry_subindustry": [],
    }
    return {**data, **overrides}


def test_valid_output_parses_and_reads_the_date():
    parsed = LLMOutput.model_validate(llm_output())
    assert parsed.date == date(2026, 4, 10)


@pytest.mark.parametrize(
    "field, value",
    [
        ("asset_tags", ["FX", "Crypto"]),
        ("primary_asset_tag", "JPY"),  # a sub-tag cannot be the primary tag
        ("bank", "DB"),
        ("industry_subindustry", ["Gas"]),  # must be the full SECTOR > Subindustry string
        ("date", "10/04/2026"),
        ("content_type", "newsletter"),
    ],
)
def test_values_outside_the_taxonomy_are_rejected(field, value):
    with pytest.raises(ValidationError):
        LLMOutput.model_validate(llm_output(**{field: value}))


def test_extra_keys_are_rejected():
    with pytest.raises(ValidationError):
        LLMOutput.model_validate(llm_output(confidence=0.9))


def test_json_schema_lists_the_allowed_tags_for_constrained_decoding():
    schema = LLMOutput.model_json_schema()
    assert schema["properties"]["primary_asset_tag"]["enum"][0] == "Macro"
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]).index("market_wrap_checklist") < list(
        schema["properties"]
    ).index("asset_tags")


def test_record_keys_follow_the_brief_exactly():
    record = ClassifiedEmail(
        folder_name="FX Daily: USD/JPY",
        bank="Deutsche Bank",
        date=date(2026, 4, 10),
        market_wrap="NO",
        primary_asset_tag="FX",
        asset_tags=["FX", "JPY"],
        companies_mentioned=[],
        industry_subindustry=[],
        pdf_attachment=None,
        source_file="035300",
        meta=Meta(),
    )
    dumped = record.model_dump(mode="json")
    assert list(dumped) == [
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
        "meta",
    ]
    assert dumped["date"] == "2026-04-10"
