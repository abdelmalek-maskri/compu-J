"""answers a person has reviewed and corrected, kept in a file so every run applies them again

a reviewed answer replaces the model's before the brief's rules run, so a market wrap set by
hand still gets the brief's fixed tags. the record says who changed what, and why
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from pipeline.allowed_tags import PRIMARY_TAGS

# the model's answers a person may correct, and the values each accepts
REVIEWABLE = {
    "market_wrap": ("YES", "NO"),
    "primary_asset_tag": PRIMARY_TAGS,
}
# notes are shown in the dashboard, so they name fields as a reader would
LABELS = {"market_wrap": "Market wrap", "primary_asset_tag": "Main asset class"}
# flags a reviewed answer settles: each questioned the answer the person has now decided
SETTLES = {
    "market_wrap": {"market_wrap", "primary_asset_tag", "companies_mentioned"},
    "primary_asset_tag": {"primary_asset_tag", "companies_mentioned"},
}


@dataclass
class Reviewed:
    field: str
    value: str
    reason: str

    def note(self) -> str:
        return f"{LABELS[self.field]} set to {self.value} by a reviewer: {self.reason}"


def load_reviewed(path: Path) -> dict[str, list[Reviewed]]:
    """by email id; a mistake in the file stops the run, so a correction is never skipped"""
    if not path.exists():
        return {}
    reviewed: dict[str, list[Reviewed]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            email, field = (row.get("email") or "").strip(), (row.get("field") or "").strip()
            value, reason = (row.get("value") or "").strip(), (row.get("reason") or "").strip()
            if not email or not reason:
                raise ValueError(f"{path} line {line}: every row needs an email and a reason")
            if field not in REVIEWABLE:
                raise ValueError(f"{path} line {line}: {field!r} cannot be reviewed here")
            if value not in REVIEWABLE[field]:
                raise ValueError(f"{path} line {line}: {value!r} is not a valid {field}")
            reviewed.setdefault(email, []).append(Reviewed(field, value, reason))
    return reviewed
