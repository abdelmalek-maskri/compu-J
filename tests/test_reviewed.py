from datetime import date

import pytest

from pipeline.build_record import build_record
from pipeline.reviewed import Reviewed, load_reviewed
from tests.factories import llm_output, prepared_email

HEADER = "email,field,value,reason\n"


def test_reviewed_answers_are_read_by_email(tmp_path):
    path = tmp_path / "reviewed.csv"
    path.write_text(HEADER + '035437,market_wrap,YES,"a weekly recap, behind a link"\n')
    assert load_reviewed(path) == {
        "035437": [Reviewed("market_wrap", "YES", "a weekly recap, behind a link")]
    }
    assert load_reviewed(tmp_path / "missing.csv") == {}


@pytest.mark.parametrize(
    "row, problem",
    [
        ("035437,market_wrap,yes,a recap", "'yes' is not a valid market_wrap"),
        ("035437,bank,UBS,a recap", "'bank' cannot be reviewed here"),
        ("035437,market_wrap,YES,", "needs an email and a reason"),
    ],
)
def test_a_mistake_in_the_file_stops_the_run(tmp_path, row, problem):
    path = tmp_path / "reviewed.csv"
    path.write_text(HEADER + row + "\n")
    with pytest.raises(ValueError, match=problem):
        load_reviewed(path)


def test_reviewed_wrap_gets_the_brief_tags_and_settles_its_flag():
    # 035437: the model chose Market Wrap as the main class but decided NO
    email = prepared_email(date=None, date_source=None, date_hint=date(2026, 4, 13))
    output = llm_output(
        date=None, date_quote=None, primary_asset_tag="Market Wrap", asset_tags=["Market Wrap"]
    )
    reviewed = [Reviewed("market_wrap", "YES", "a weekly recap behind a link")]
    record = build_record(email, output, "model", "v2", reviewed)

    assert (record.market_wrap, record.primary_asset_tag, record.asset_tags) == (
        "YES",
        "Market Wrap",
        ["Market Wrap"],
    )
    assert record.meta.reviewed == [
        "Market wrap set to YES by a reviewer: a weekly recap behind a link"
    ]
    # the contradiction is settled; the date has nothing to do with it and stays flagged
    assert [f.field for f in record.meta.flags] == ["date"]


def test_without_a_review_the_model_answer_stands():
    output = llm_output(primary_asset_tag="Market Wrap", asset_tags=["Market Wrap"])
    record = build_record(prepared_email(), output, "model", "v2")
    assert (record.market_wrap, record.meta.reviewed) == ("NO", [])
    assert "primary_asset_tag" in [f.field for f in record.meta.flags]
