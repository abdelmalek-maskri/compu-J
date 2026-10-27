"""title, bank and date: the model's answer wins when the email confirms it.

Python backs up the bank. For the date it only checks: a date the rules find but the model
rejects is another kind of date ("as of", an article's, a deadline), so it is never used alone"""

import re
from dataclasses import dataclass
from datetime import date

from pipeline.clean_emails import (
    BANK_PATTERNS,
    RECEIVED_MARGIN,
    PreparedEmail,
    could_be_published,
    find_date,
    weekday_date,
)
from pipeline.schema import LLMOutput


@dataclass
class Metadata:
    title: str
    title_verified: bool
    bank: str | None
    bank_source: str | None
    date: date | None
    # "llm+python", "llm", or "link" for an unconfirmed date from a link address
    date_source: str | None
    date_quote: str | None
    # why the model's date was not used (see _date_problem), for the flag's note
    date_problem: str | None
    received: date | None
    # both answers are kept, so the two methods can be compared on every email (see flags.py)
    bank_llm: str
    bank_python: str | None
    date_llm: date | None
    date_python: date | None
    date_python_source: str | None


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


def _date_problem(email: PreparedEmail, said: date, quote: str | None) -> str | None:
    """why the model's date cannot be confirmed as the publication date; None when it can"""
    if email.received and said > email.received + RECEIVED_MARGIN:
        return "after_arrival"
    if not could_be_published(said, email.received):
        return "too_old"
    if not appears_in(quote, email.llm_input):
        return "not_in_email"
    stated = find_date(quote, [])[0] or weekday_date(quote, email.received or said)
    return None if stated == said else "no_full_date"


def _choose_date(
    email: PreparedEmail, said: date | None, quote: str | None
) -> tuple[date | None, str | None, str | None]:
    """returns (date, source, problem)"""
    problem = _date_problem(email, said, quote) if said else None
    # both readers finding the same date confirms it, even when the model's quote falls short
    if said and (problem is None or said == email.date):
        return said, "llm+python" if said == email.date else "llm", None
    if email.date_hint:
        return email.date_hint, "link", problem
    return None, None, problem


def check_metadata(email: PreparedEmail, output: LLMOutput) -> Metadata:
    bank, bank_source = _choose_bank(email, output.bank)
    found, date_source, date_problem = _choose_date(email, output.date, output.date_quote)
    return Metadata(
        title=output.title,
        title_verified=appears_in(output.title, email.llm_input),
        bank=bank,
        bank_source=bank_source,
        date=found,
        date_source=date_source,
        date_quote=output.date_quote,
        date_problem=date_problem,
        received=email.received,
        bank_llm=output.bank,
        bank_python=email.bank,
        date_llm=output.date,
        date_python=email.date,
        date_python_source=email.date_source,
    )
