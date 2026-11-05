import pytest

from rag.footers import cut_footer, load_footers
from rag.ingest import build_sources
from tests.factories import prepared_email

BANKS = {"Goldman Sachs", "UBS"}


def write(tmp_path, text: str):
    path = tmp_path / "footers.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_no_file_cuts_nothing(tmp_path):
    assert load_footers(tmp_path / "footers.csv", BANKS) == {}


def test_footer_starts_are_read_by_bank(tmp_path):
    path = write(tmp_path, "bank,starts_with\nGoldman Sachs,Prepared by a Goldman Sachs sales\n"
                           'UBS,"UBS 2026.  The key symbol"\n')  # fmt: skip
    assert load_footers(path, BANKS) == {
        "Goldman Sachs": ["prepared by a goldman sachs sales"],
        "UBS": ["ubs 2026. the key symbol"],
    }


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("bank,marker\nUBS,x\n", "first line"),
        ("bank,starts_with\nUBS,\n", "needs a bank"),
        ("bank,starts_with\nBarclays,Disclaimer\n", "no bank 'Barclays'"),
        ("bank,starts_with\nUBS,Disclaimer\nUBS,disclaimer\n", "already has"),
    ],
)
def test_a_mistake_in_the_file_stops_the_run(tmp_path, text, problem):
    with pytest.raises(ValueError, match=problem):
        load_footers(write(tmp_path, text), BANKS)


def test_an_email_is_cut_from_its_first_footer_line():
    body = "Flows were strong.\nSean Vogel\nPrepared by a Goldman Sachs sales desk.\nOptions risk."
    assert (
        cut_footer(body, ["prepared by a goldman sachs sales"]) == "Flows were strong.\nSean Vogel"
    )


def test_a_leading_copyright_sign_is_ignored_and_no_match_keeps_everything():
    body = "Recap of the week.\n\u00a9 UBS 2026. The key symbol and UBS are trademarks."
    assert cut_footer(body, ["ubs 2026. the key symbol"]) == "Recap of the week."
    assert cut_footer(body, ["disclaimer"]) == body


def test_only_a_banks_own_footer_starts_are_used(tmp_path):
    footer = "Disclaimer\nThis note is not advice."
    goldman = prepared_email(id="035300", bank="Goldman Sachs", body=f"Fed view.\n{footer}")
    ubs = prepared_email(id="035301", bank="UBS", body=f"Gold view.\n{footer}")
    sources, _ = build_sources([goldman, ubs], {}, tmp_path, {"UBS": ["disclaimer"]})
    assert [s.text for s in sources] == [f"Fed view.\n{footer}", "Gold view."]
