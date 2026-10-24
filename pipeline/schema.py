"""what the LLM must return, and the record written to classified_emails.json"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.taxonomy import ASSET_TAGS, BANK_NAMES, INDUSTRY_TAGS, PRIMARY_TAGS

PrimaryTag = Literal[PRIMARY_TAGS]
AssetTag = Literal[ASSET_TAGS]
IndustryTag = Literal[INDUSTRY_TAGS]
BankName = Literal[BANK_NAMES]
ContentType = Literal["research", "event", "marketing"]


class MarketWrapChecklist(BaseModel):
    """the brief's seven checklist groups; rules.py turns the answers into YES or NO"""

    model_config = ConfigDict(extra="forbid")

    structure: bool
    asset_coverage: bool
    timeframe: bool
    purpose: bool
    title: bool
    language: bool
    depth: bool


class LLMOutput(BaseModel):
    # forbidding extra keys also tells constrained decoding the object is closed
    model_config = ConfigDict(extra="forbid")

    title: str
    bank: BankName
    date: date | None
    date_quote: str | None
    content_type: ContentType
    # before the tags on purpose: the model writes fields in this order, and the brief
    # decides market wrap first
    market_wrap_checklist: MarketWrapChecklist
    primary_asset_tag: PrimaryTag
    asset_tags: list[AssetTag]
    companies_mentioned: list[str]
    industry_subindustry: list[IndustryTag]


class Meta(BaseModel):
    """everything beyond the brief's fields, kept apart so the required keys stay exact"""

    bank_source: str | None = None
    date_source: str | None = None
    date_quote: str | None = None
    received: date | None = None
    title_verified: bool | None = None
    conflicts: list[str] = []
    corrections: list[str] = []
    content_type: ContentType | None = None
    market_wrap_checklist: MarketWrapChecklist | None = None
    duplicate_of: str | None = None
    warnings: list[str] = []
    error: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class ClassifiedEmail(BaseModel):
    """one entry of classified_emails.json; field names and order follow the brief"""

    folder_name: str | None
    bank: str | None
    date: date | None
    market_wrap: Literal["YES", "NO"] | None
    primary_asset_tag: PrimaryTag | None
    asset_tags: list[AssetTag]
    companies_mentioned: list[str]
    industry_subindustry: list[IndustryTag]
    pdf_attachment: list[str] | None
    source_file: str
    meta: Meta
