"""find what a person should look at, and write it to a review file

each email is read twice: by the AI model, and by fixed rules written in Python (the bank from
the logo or signature, the date from the top of the email or a PDF's name). notes are written
for someone who knows neither, because they are shown in the dashboard and in review.csv

model_vs_python: the model and the rules gave different answers
model_logic:     the model's answer contradicts itself
model_vs_model:  two models disagree on the same email (made by scripts/compare_models.py)
inferred:        a value was inferred rather than stated, so a person should confirm it
"""

import csv
from datetime import date
from pathlib import Path

from pipeline.allowed_tags import EQUITY, MARKET_WRAP, SUB_TO_PARENT
from pipeline.check_metadata import Metadata, appears_in
from pipeline.schema import ClassifiedEmail, Flag, LLMOutput

# these only decide when to ask a person to look, never what the answer is
FEW_CHECKS_FOR_A_WRAP = 2
MANY_CHECKS_FOR_A_NON_WRAP = 6


def _text(value: date | str | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else value


# where the rules found a value, from Metadata's "python:<where>" sources
WHERE = {
    "logo": "the bank's logo",
    "signature": "the signature",
    "top_text": "the top of the email",
    "text": "the email's text",
    "pdf_name": "a PDF's file name",
}


def _day(value: date) -> str:
    return f"{value.day} {value:%B %Y}"


def _where(source: str | None) -> str:
    where = (source or "").removeprefix("python:")
    return WHERE.get(where, where)


def metadata_flags(meta: Metadata) -> list[Flag]:
    flags = []
    # the model naming a bank the rules did not find is filling a gap, not disagreeing
    filled_gap = meta.bank_python is None and meta.bank == meta.bank_llm
    if meta.bank_llm != "Other" and meta.bank_llm != meta.bank_python and not filled_gap:
        note = f"The AI says {meta.bank_llm}; the rules say {meta.bank_python or 'no bank'}. "
        if meta.bank == meta.bank_llm:
            note += "Kept the AI's answer, because the email names that bank."
        else:
            note += "Kept the rules' answer, because the AI's bank is not named in the email."
        flags.append(
            Flag(
                kind="model_vs_python",
                field="bank",
                value_a=meta.bank_llm,
                value_b=meta.bank_python,
                note=note,
            )
        )

    filled_gap = meta.date_python is None and meta.date == meta.date_llm
    if meta.date_llm and meta.date_llm != meta.date_python and not filled_gap:
        rules = _day(meta.date_python) if meta.date_python else "no date"
        if meta.date == meta.date_llm:
            note = (
                f"The AI dated it {_day(meta.date_llm)}; the rules found {rules}. Kept the AI's "
                f"date, because the email states it ('{meta.date_quote}')."
            )
        else:
            note = (
                f"The AI dated it {_day(meta.date_llm)}, quoting '{meta.date_quote}', but that "
                "could not be confirmed: the quote must be in the email, give the full date, "
                "and fall between a month before the email arrived and a day after. "
            )
            note += (
                f"Kept the rules' date, found in {_where(meta.date_source)}."
                if meta.date
                else "The date was left empty."
            )
        flags.append(
            Flag(
                kind="model_vs_python",
                field="date",
                value_a=_text(meta.date_llm),
                value_b=_text(meta.date_python),
                note=note,
            )
        )

    # the model saying there is no publication date is a disagreement too: 035274's rules date
    # is an "as of" date the model rightly refused
    if meta.date_llm is None and meta.date_python:
        flags.append(
            Flag(
                kind="model_vs_python",
                field="date",
                value_b=_text(meta.date_python),
                note=f"The AI found no publication date; the rules found {_day(meta.date_python)} "
                f"in {_where(meta.date_source)}. Kept it, but it may be another kind of date, "
                "such as the day data is 'as of'.",
            )
        )

    if not meta.title_verified:
        flags.append(
            Flag(
                kind="model_vs_python",
                field="title",
                value_a=meta.title,
                note="The AI's title could not be found in the email, word for word.",
            )
        )
    return flags


def hint_flags(date_found: date | None, hint: date | None) -> list[Flag]:
    if date_found or not hint:
        return []
    return [
        Flag(
            kind="inferred",
            field="date",
            value_a=_text(hint),
            note=f"The email states no date. A link in it contains {_day(hint)}, probably the "
            "day it was sent; shown as a hint, not used as the date.",
        )
    ]


def logic_flags(output: LLMOutput) -> list[Flag]:
    flags = []
    checks = output.market_wrap_checklist.model_dump()
    yes = sum(checks.values())

    def wrap_flag(value_b: str, note: str) -> None:
        flags.append(
            Flag(
                kind="model_logic",
                field="market_wrap",
                value_a=output.market_wrap,
                value_b=value_b,
                note=note,
            )
        )

    if output.market_wrap == "NO" and output.primary_asset_tag == MARKET_WRAP:
        others = [t for t in output.asset_tags if t != MARKET_WRAP]
        note = (
            "The AI gave Market Wrap as the main asset class, but decided the email is not a "
            "market wrap. The Market Wrap tag was removed"
        )
        flags.append(
            Flag(
                kind="model_logic",
                field="primary_asset_tag",
                value_a=MARKET_WRAP,
                value_b="decision: NO",
                note=note + "." if others else note + ", leaving no main asset class.",
            )
        )

    if output.market_wrap == "YES":
        if not checks["purpose"]:
            wrap_flag(
                "purpose: no",
                "The AI called this a market wrap, but its own checklist says the email does more "
                "than recap what happened. A market wrap only recaps.",
            )
        if yes <= FEW_CHECKS_FOR_A_WRAP:
            wrap_flag(
                f"{yes}/7 checks",
                f"The AI called this a market wrap, but only {yes} of the brief's 7 market wrap "
                "checks were met.",
            )
        if output.content_type != "research":
            wrap_flag(
                f"content type: {output.content_type}",
                f"The AI called this a market wrap, but also says it is {output.content_type}, "
                "not research. A market wrap is a recap of the markets.",
            )
    elif yes >= MANY_CHECKS_FOR_A_NON_WRAP:
        wrap_flag(
            f"{yes}/7 checks",
            f"The AI decided this is not a market wrap, although {yes} of the brief's 7 market "
            "wrap checks were met.",
        )

    classes = {SUB_TO_PARENT.get(t, t) for t in [output.primary_asset_tag, *output.asset_tags]}
    if output.market_wrap == "NO" and output.companies_mentioned and EQUITY not in classes:
        flags.append(
            Flag(
                kind="model_logic",
                field="companies_mentioned",
                value_a=f"{len(output.companies_mentioned)} companies",
                value_b=f"primary tag: {output.primary_asset_tag}",
                note=f"The AI named {len(output.companies_mentioned)} companies but did not tag "
                "the email as Equity. The brief lists companies only for Equity, so they were "
                "dropped.",
            )
        )

    has_quote = bool(output.date_quote and output.date_quote.strip())
    if (output.date is None) == has_quote:
        flags.append(
            Flag(
                kind="model_logic",
                field="date",
                value_a=_text(output.date),
                value_b=output.date_quote,
                note="The AI gave a date without quoting where it appears, or a quote without a "
                "date.",
            )
        )
    return flags


# fields compared between two models; lists are compared as sets, titles ignoring spacing and case
COMPARED_FIELDS = [
    "market_wrap",
    "primary_asset_tag",
    "asset_tags",
    "bank",
    "date",
    "folder_name",
    "companies_mentioned",
    "industry_subindustry",
]


def _value(record: ClassifiedEmail, field: str) -> str | None:
    value = getattr(record, field)
    if isinstance(value, list):
        return ", ".join(
            sorted(v.casefold() if field == "companies_mentioned" else v for v in value)
        )
    return _text(value)


def same_answer(a: ClassifiedEmail, b: ClassifiedEmail, field: str) -> bool:
    if field == "folder_name":
        return a.folder_name == b.folder_name or (
            appears_in(a.folder_name, b.folder_name or "")
            and appears_in(b.folder_name, a.folder_name or "")
        )
    return _value(a, field) == _value(b, field)


def model_vs_model_flags(
    a: ClassifiedEmail, b: ClassifiedEmail, name_a: str, name_b: str
) -> list[Flag]:
    """one flag per field where two models answered the same email differently"""
    return [
        Flag(
            kind="model_vs_model",
            field=field,
            value_a=_value(a, field),
            value_b=_value(b, field),
            note=f"{name_a} and {name_b} answered differently.",
        )
        for field in COMPARED_FIELDS
        if not same_answer(a, b, field)
    ]


REVIEW_COLUMNS = [
    "email", "title", "model", "kind", "field", "value_a", "value_b", "note", "your_verdict",
]  # fmt: skip


def review_rows(records: list[ClassifiedEmail], model: str) -> list[dict]:
    """each record's own flags; model says who raised them (a model, or "a vs b")"""
    return [
        {
            "email": r.source_file,
            "title": r.folder_name,
            "model": model,
            **flag.model_dump(),
            "your_verdict": "",
        }
        for r in records
        for flag in r.meta.flags
    ]


def write_review(rows: list[dict], path: Path) -> None:
    """a spreadsheet with an empty verdict column: reviewing it also produces hand labels"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
