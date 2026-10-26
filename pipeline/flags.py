"""find what a person should look at, and write it to a review file

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


def metadata_flags(meta: Metadata) -> list[Flag]:
    flags = []
    # the model naming a bank the rules did not find is filling a gap, not disagreeing
    filled_gap = meta.bank_python is None and meta.bank == meta.bank_llm
    if meta.bank_llm != "Other" and meta.bank_llm != meta.bank_python and not filled_gap:
        note = f"kept {meta.bank} ({meta.bank_source})"
        if meta.bank != meta.bank_llm:
            note += ", the model's bank is not named in the email"
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
        note = f"kept {_text(meta.date)} ({meta.date_source})"
        if meta.date != meta.date_llm:
            note += (
                f", the model's date did not check out (quote {meta.date_quote!r}: missing, "
                "another date, or outside the arrival window)"
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
                note="the model found no publication date; "
                f"kept the rules' date ({meta.date_source})",
            )
        )

    if not meta.title_verified:
        flags.append(
            Flag(
                kind="model_vs_python",
                field="title",
                value_a=meta.title,
                note="the model's title is not in the email",
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
            note="the email states no date; this one is inferred from a link address",
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
            "named Market Wrap as the main class but decided it is not a wrap; the tag was removed"
        )
        flags.append(
            Flag(
                kind="model_logic",
                field="primary_asset_tag",
                value_a=MARKET_WRAP,
                value_b="decision: NO",
                note=note if others else note + ", leaving no asset class",
            )
        )

    if output.market_wrap == "YES":
        if not checks["purpose"]:
            wrap_flag(
                "purpose: no",
                "a wrap is descriptive with no forward-looking view, "
                "yet the model says this email's purpose is not",
            )
        if yes <= FEW_CHECKS_FOR_A_WRAP:
            wrap_flag(f"{yes}/7 checks", "decided wrap against most of its own checklist")
        if output.content_type != "research":
            wrap_flag(f"content type: {output.content_type}", "an event or offer is not a recap")
    elif yes >= MANY_CHECKS_FOR_A_NON_WRAP:
        wrap_flag(f"{yes}/7 checks", "decided not a wrap against most of its own checklist")

    classes = {SUB_TO_PARENT.get(t, t) for t in [output.primary_asset_tag, *output.asset_tags]}
    if output.market_wrap == "NO" and output.companies_mentioned and EQUITY not in classes:
        flags.append(
            Flag(
                kind="model_logic",
                field="companies_mentioned",
                value_a=f"{len(output.companies_mentioned)} companies",
                value_b=f"primary tag: {output.primary_asset_tag}",
                note="named companies but gave no Equity tag, so they were dropped",
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
                note="a date without a quote, or a quote without a date",
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
            note=f"{name_a} vs {name_b}",
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
