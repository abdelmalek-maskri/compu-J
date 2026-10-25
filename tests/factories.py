"""builders for test data shared across test files"""

from datetime import date

from pipeline.clean_emails import Attachments, PreparedEmail
from pipeline.schema import LLMOutput

CHECKS = ["structure", "asset_coverage", "timeframe", "purpose", "title", "language", "depth"]


def checklist(yes: int = 0) -> dict[str, bool]:
    """the first `yes` checklist groups answered true"""
    return {name: i < yes for i, name in enumerate(CHECKS)}


def llm_output_data(**overrides) -> dict:
    data = {
        "title": "FX Daily: USD/JPY",
        "bank": "Deutsche Bank",
        "date": "2026-04-10",
        "date_quote": "10 April 2026",
        "content_type": "research",
        "market_wrap_checklist": checklist(),
        "primary_asset_tag": "FX",
        "asset_tags": ["FX", "JPY"],
        "companies_mentioned": [],
        "industry_subindustry": [],
    }
    return {**data, **overrides}


def llm_output(**overrides) -> LLMOutput:
    return LLMOutput.model_validate(llm_output_data(**overrides))


def prepared_email(**overrides) -> PreparedEmail:
    data = {
        "id": "035300",
        "body": "[image: Deutsche Bank Logo]\nFX Daily: USD/JPY\n10 April 2026\nWe stay short.",
        "llm_input": "",
        "attachments": Attachments([], [], {}),
        "bank": "Deutsche Bank",
        "bank_source": "logo",
        "date": date(2026, 4, 10),
        "date_source": "text",
        "received": None,
        "encoding": "utf-8",
    }
    data |= overrides
    data["llm_input"] = data["llm_input"] or f"EMAIL BODY:\n{data['body']}\n\nATTACHMENTS: none"
    return PreparedEmail(**data)
