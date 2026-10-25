"""what the LLM must return, and the record written to classified_emails.json"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.allowed_tags import ASSET_TAGS, BANK_NAMES, INDUSTRY_TAGS, PRIMARY_TAGS

PrimaryTag = Literal[PRIMARY_TAGS]
AssetTag = Literal[ASSET_TAGS]
IndustryTag = Literal[INDUSTRY_TAGS]
BankName = Literal[BANK_NAMES]
ContentType = Literal["research", "event", "marketing"]


class MarketWrapChecklist(BaseModel):
    """the brief's seven checklist groups, answered by the model before it decides"""

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
    # the model's own decision; the checklist above is kept as its reasons
    market_wrap: Literal["YES", "NO"]
    primary_asset_tag: PrimaryTag
    asset_tags: list[AssetTag]
    companies_mentioned: list[str]
    industry_subindustry: list[IndustryTag]


class Flag(BaseModel):
    """something a person should look at: two answers that disagree, or an answer that
    contradicts itself. corrections the rules make on their own are not flags"""

    kind: Literal["model_vs_python", "model_logic", "model_vs_model"]
    field: str
    value_a: str | None = None
    value_b: str | None = None
    note: str


class Meta(BaseModel):
    """everything beyond the brief's fields, kept apart so the required keys stay exact"""

    bank_source: str | None = None
    date_source: str | None = None
    date_quote: str | None = None
    received: date | None = None
    title_verified: bool | None = None
    # both answers kept on every record, so the model and the rules can be compared
    bank_llm: str | None = None
    bank_python: str | None = None
    date_llm: date | None = None
    date_python: date | None = None
    flags: list[Flag] = []
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
