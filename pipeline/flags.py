"""find what a person should look at, and write it to a review file

model_vs_python: the model and the rules gave different answers
model_logic:     the model's answer contradicts itself
model_vs_model:  two models disagree on the same email (made by scripts/compare_models.py)
"""

import csv
from datetime import date
from pathlib import Path

from pipeline.allowed_tags import EQUITY, SUB_TO_PARENT
from pipeline.check_metadata import Metadata
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


REVIEW_COLUMNS = ["email", "title", "kind", "field", "value_a", "value_b", "note", "your_verdict"]


def review_rows(records: list[ClassifiedEmail]) -> list[dict]:
    return [
        {"email": r.source_file, "title": r.folder_name, **flag.model_dump(), "your_verdict": ""}
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
