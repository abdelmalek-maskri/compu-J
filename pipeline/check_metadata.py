"""title, bank and date: the model's answer wins when the email confirms it, Python backs up"""

import re
from dataclasses import dataclass
from datetime import date

from pipeline.clean_emails import BANK_PATTERNS, PreparedEmail, could_be_published, find_date
from pipeline.schema import LLMOutput


@dataclass
class Metadata:
    title: str
    title_verified: bool
    bank: str | None
    bank_source: str | None
    date: date | None
    date_source: str | None
    date_quote: str | None
    # both answers are kept, so the two methods can be compared on every email (see flags.py)
    bank_llm: str
    bank_python: str | None
    date_llm: date | None
    date_python: date | None


# removed inside words: the export replaced lost apostrophes with \ufffd, and models retype
# them as plain ones or drop them, so "Europe\ufffds", "Europe's" and "Europes" must all match
INSIDE_WORD = re.compile(r"['\u2018\u2019\ufffd]")


def _words(text: str) -> str:
    """lower case words only; other punctuation and spacing do not count"""
    return " ".join(re.findall(r"\w+", INSIDE_WORD.sub("", text.casefold())))


def appears_in(snippet: str | None, text: str) -> bool:
    """the snippet's words appear in the text, in order and as whole words"""
    words = _words(snippet or "")
    return bool(words) and f" {words} " in f" {_words(text)} "


def _choose_bank(email: PreparedEmail, said: str) -> tuple[str | None, str | None]:
    """returns (bank, source); "Other" means the model was unsure"""
    pattern = BANK_PATTERNS.get(said)
    if pattern and pattern.search(email.llm_input):
        return said, "llm+python" if said == email.bank else "llm"
    if email.bank:
        return email.bank, f"python:{email.bank_source}"
    return ("Other", "llm") if said == "Other" else (None, None)


def _date_checks_out(email: PreparedEmail, said: date, quote: str | None) -> bool:
    return (
        appears_in(quote, email.llm_input)
        and find_date(quote, [])[0] == said
        and could_be_published(said, email.received)
    )


def _choose_date(
    email: PreparedEmail, said: date | None, quote: str | None
) -> tuple[date | None, str | None]:
    """returns (date, source)"""
    if said and _date_checks_out(email, said, quote):
        return said, "llm+python" if said == email.date else "llm"
    if email.date:
        return email.date, f"python:{email.date_source}"
    return None, None


def check_metadata(email: PreparedEmail, output: LLMOutput) -> Metadata:
    bank, bank_source = _choose_bank(email, output.bank)
    found, date_source = _choose_date(email, output.date, output.date_quote)
    return Metadata(
        title=output.title,
        title_verified=appears_in(output.title, email.llm_input),
        bank=bank,
        bank_source=bank_source,
        date=found,
        date_source=date_source,
        date_quote=output.date_quote,
        bank_llm=output.bank,
        bank_python=email.bank,
        date_llm=output.date,
        date_python=email.date,
    )
