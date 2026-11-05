"""cut each bank's legal footer off its emails, from where a person says it starts

the rules in rag/chunks.py remove legal lines one at a time, by repetition and wording, and miss
a paragraph whose words are not on the list ("Market Making, Investing and Lending: Goldman
Sachs engages in...") or a disclaimer sharing a line with analysts' names. but a bank's footer
is one block at the end of its emails, starting with the same sentence each time. so a person
writes down that sentence for each bank in evaluation/footers.csv, and every email of that bank
is cut from the first line starting with it to the end. like reviewed.csv for the classifier,
the decision is a person's and the code applies it on every run; a mistake in the file stops
the run, so a cut is never silently skipped
"""

import csv
import re
from pathlib import Path

from rag.chunks import _normal

COLUMNS = ["bank", "starts_with"]
# a footer line can start with a copyright sign, or the replacement sign the export left for it
LEADING = re.compile(r"^\W+")


def load_footers(path: Path, known_banks: set[str]) -> dict[str, list[str]]:
    """by bank, the normalised starts of its footers; no file means no footer is cut"""
    if not path.exists():
        return {}
    footers: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path}: the first line must be {','.join(COLUMNS)}")
        for line, row in enumerate(reader, start=2):
            bank, start = (row["bank"] or "").strip(), _normal(row["starts_with"] or "")
            if not bank or not start:
                raise ValueError(f"{path} line {line}: every row needs a bank and its footer start")
            if bank not in known_banks:
                raise ValueError(f"{path} line {line}: no bank {bank!r} in the data")
            if start in footers.get(bank, []):
                raise ValueError(f"{path} line {line}: {bank} already has this footer start")
            footers.setdefault(bank, []).append(start)
    return footers


def cut_footer(text: str, starts: list[str]) -> str:
    """the text before the first line that starts like a footer, or all of it"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(LEADING.sub("", _normal(line)).startswith(start) for start in starts):
            return "\n".join(lines[:i])
    return text
