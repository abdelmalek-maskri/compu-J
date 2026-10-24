"""combine Python's and the model's title, bank and date into one answer with its evidence"""

from dataclasses import dataclass, field
from datetime import date

from pipeline.prepare import PreparedEmail, could_be_published, find_date
from pipeline.schema import LLMOutput

# models often retype curly quotes and dashes as plain ones when copying text
PLAIN_PUNCTUATION = str.maketrans(
    {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"}
)


@dataclass
class Metadata:
    title: str
    title_verified: bool
    bank: str | None
    bank_source: str | None
    date: date | None
    date_source: str | None
    date_quote: str | None
    conflicts: list[str] = field(default_factory=list)


def _normalise(text: str) -> str:
    return " ".join(text.translate(PLAIN_PUNCTUATION).split()).casefold()


def appears_in(snippet: str | None, text: str) -> bool:
    return bool(snippet and snippet.strip()) and _normalise(snippet) in _normalise(text)


def _merge_bank(email: PreparedEmail, said: str) -> tuple[str | None, str | None, str | None]:
    """returns (bank, source, conflict); "Other" from the model means it was unsure"""
    if email.bank:
        if said == email.bank:
            return email.bank, f"{email.bank_source}+llm", None
        if said == "Other":
            return email.bank, email.bank_source, None
        return email.bank, email.bank_source, f"bank: rules found {email.bank}, model said {said}"
    return said, "llm", None


def _quote_backs_date(email: PreparedEmail, said: date, quote: str | None) -> bool:
    return (
        appears_in(quote, email.llm_input)
        and find_date(quote, [])[0] == said
        and could_be_published(said, email.received)
    )


def _merge_date(
    email: PreparedEmail, said: date | None, quote: str | None
) -> tuple[date | None, str | None, str | None]:
    """returns (date, source, conflict); the model only fills a gap when its quote checks out"""
    if said is None:
        return email.date, email.date_source, None
    if email.date:
        if said == email.date:
            return email.date, f"{email.date_source}+llm", None
        return email.date, email.date_source, f"date: rules found {email.date}, model said {said}"
    if _quote_backs_date(email, said, quote):
        return said, "llm", None
    return None, None, f"date: model said {said} quoting {quote!r}, which does not check out"


def merge_metadata(email: PreparedEmail, output: LLMOutput) -> Metadata:
    bank, bank_source, bank_conflict = _merge_bank(email, output.bank)
    found, date_source, date_conflict = _merge_date(email, output.date, output.date_quote)
    return Metadata(
        title=output.title,
        title_verified=appears_in(output.title, email.llm_input),
        bank=bank,
        bank_source=bank_source,
        date=found,
        date_source=date_source,
        date_quote=output.date_quote,
        conflicts=[c for c in (bank_conflict, date_conflict) if c],
    )
