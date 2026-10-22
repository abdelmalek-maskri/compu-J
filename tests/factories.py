"""builders for test data shared across test files"""

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
