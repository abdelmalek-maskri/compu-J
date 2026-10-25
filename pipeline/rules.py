"""the brief's tagging rules, applied to whatever the LLM returned"""

from dataclasses import dataclass, field
from typing import Literal

from pipeline.schema import LLMOutput, MarketWrapChecklist
from pipeline.taxonomy import EQUITY, MARKET_WRAP, PRIMARY_TAGS, SUB_TO_PARENT, UNKNOWN_INDUSTRY

# out of the 7 checklist groups; the brief gives no threshold, so this gets tuned on labelled emails
MARKET_WRAP_THRESHOLD = 5


@dataclass
class Tags:
    market_wrap: Literal["YES", "NO"]
    primary_asset_tag: str | None
    asset_tags: list[str]
    companies_mentioned: list[str]
    industry_subindustry: list[str]
    corrections: list[str] = field(default_factory=list)


def is_market_wrap(checklist: MarketWrapChecklist) -> bool:
    return sum(checklist.model_dump().values()) >= MARKET_WRAP_THRESHOLD


def normalise_tags(primary: str, tags: list[str]) -> tuple[list[str], list[str]]:
    """primary first, each sub-tag after its parent, no repeats; returns (tags, corrections)"""
    result, corrections = [], []
    for tag in [primary, *tags]:
        parent = SUB_TO_PARENT.get(tag)
        if parent and parent not in result:
            result.append(parent)
            if parent not in tags:
                corrections.append(f"added parent {parent} for {tag}")
        if tag not in result:
            result.append(tag)
    return result, corrections


def clean_companies(companies: list[str]) -> list[str]:
    result, seen = [], set()
    for name in companies:
        name = " ".join(name.split())
        if name and name.lower() not in seen:
            seen.add(name.lower())
            result.append(name)
    return result


def apply_equity_rules(
    tags: list[str], companies: list[str], industries: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """returns (companies, industries, corrections)"""
    if EQUITY not in tags:
        dropped = ["dropped companies and industries without an Equity tag"]
        return [], [], dropped if companies or industries else []
    real = [i for i in dict.fromkeys(industries) if i != UNKNOWN_INDUSTRY]
    return clean_companies(companies), real or [UNKNOWN_INDUSTRY], []


def apply_tag_rules(output: LLMOutput) -> Tags:
    if is_market_wrap(output.market_wrap_checklist):
        return Tags("YES", MARKET_WRAP, [MARKET_WRAP], [], [])

    corrections = []
    primary, tags = output.primary_asset_tag, list(output.asset_tags)
    if MARKET_WRAP in [primary, *tags]:
        corrections.append("removed Market Wrap: checklist below threshold")
        tags = [t for t in tags if t != MARKET_WRAP]
        if primary == MARKET_WRAP:
            # promote the first other class the model named, parents of sub-tags included
            named = [SUB_TO_PARENT.get(t, t) for t in tags]
            primary = next((t for t in named if t in PRIMARY_TAGS), None)
    if primary is None:
        corrections.append("no asset class left after removing Market Wrap")
        return Tags("NO", None, [], [], [], corrections)

    tags, added = normalise_tags(primary, tags)
    companies, industries, dropped = apply_equity_rules(
        tags, output.companies_mentioned, output.industry_subindustry
    )
    return Tags("NO", primary, tags, companies, industries, corrections + added + dropped)
