"""answers a person has reviewed and corrected, kept in a file so every run applies them again

a reviewed answer replaces the model's before the brief's rules run, so a market wrap set by
hand still gets the brief's fixed tags. the record says who changed what, what the model had
said, and why
"""

import csv
from dataclasses import dataclass
from pathlib import Path

COLUMNS = ["email", "field", "value", "reason"]
# the answers a person may correct, and the values each accepts (None: any text). the main
# asset class is left out on purpose: the market wrap rules decide it, so correcting it alone
# could be undone
REVIEWABLE = {"market_wrap": ("YES", "NO"), "folder_name": None}
# notes are shown in the dashboard, so they name fields as a reader would
LABELS = {"market_wrap": "Market wrap", "folder_name": "Title"}
# where the model's own answer is, when its name differs from the record's
MODEL_FIELDS = {"folder_name": "title"}


@dataclass
class Reviewed:
    field: str
    value: str
    reason: str

    @property
    def model_field(self) -> str:
        return MODEL_FIELDS.get(self.field, self.field)

    def note(self, model_said: str | None) -> str:
        return (
            f"{LABELS[self.field]} set to {self.value} by a reviewer (the AI said "
            f"{model_said}): {self.reason}"
        )

    def settles(self) -> set[str]:
        """the flags this answer settles: those that questioned what the person decided. a
        market wrap has the brief's fixed class and no companies, so YES settles those too"""
        if self.field == "folder_name":
            return {"title"}
        if self.value == "YES":
            return {"market_wrap", "primary_asset_tag", "companies_mentioned"}
        return {"market_wrap"}


def load_reviewed(path: Path, known: set[str]) -> dict[str, list[Reviewed]]:
    """by email id; any mistake in the file stops the run, so a correction is never skipped"""
    if not path.exists():
        return {}
    reviewed: dict[str, list[Reviewed]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        # without its header, the first correction would be read as the header and lost
        if rows.fieldnames != COLUMNS:
            raise ValueError(f"{path}: the first line must be {','.join(COLUMNS)}")
        for line, row in enumerate(rows, start=2):
            email, field = (row["email"] or "").strip(), (row["field"] or "").strip()
            value, reason = (row["value"] or "").strip(), (row["reason"] or "").strip()
            if not email or not value or not reason:
                raise ValueError(
                    f"{path} line {line}: every row needs an email, a value and a reason"
                )
            if email not in known:
                raise ValueError(f"{path} line {line}: no email {email!r} in the data")
            if field not in REVIEWABLE:
                raise ValueError(f"{path} line {line}: {field!r} cannot be reviewed here")
            if REVIEWABLE[field] is not None and value not in REVIEWABLE[field]:
                raise ValueError(f"{path} line {line}: {value!r} is not a valid {field}")
            if any(r.field == field for r in reviewed.get(email, [])):
                raise ValueError(f"{path} line {line}: {email} {field} is already corrected")
            reviewed.setdefault(email, []).append(Reviewed(field, value, reason))
    return reviewed
