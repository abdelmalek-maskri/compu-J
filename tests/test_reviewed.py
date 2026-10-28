from datetime import date

import pytest

from pipeline.build_record import build_record
from pipeline.reviewed import Reviewed, load_reviewed
from tests.factories import llm_output, prepared_email

HEADER = "email,field,value,reason\n"
KNOWN = {"035437", "035438"}


def write(tmp_path, text):
    path = tmp_path / "reviewed.csv"
    path.write_text(text)
    return path


def test_reviewed_answers_are_read_by_email(tmp_path):
    path = write(tmp_path, HEADER + '035437,market_wrap,YES,"a weekly recap, behind a link"\n')
    assert load_reviewed(path, KNOWN) == {
        "035437": [Reviewed("market_wrap", "YES", "a weekly recap, behind a link")]
    }
    assert load_reviewed(tmp_path / "missing.csv", KNOWN) == {}


@pytest.mark.parametrize(
    "text, problem",
    [
        (HEADER + "035437,market_wrap,yes,a recap\n", "'yes' is not a valid market_wrap"),
        (HEADER + "035437,bank,UBS,a recap\n", "'bank' cannot be reviewed here"),
        (HEADER + "035437,primary_asset_tag,Macro,a recap\n", "cannot be reviewed here"),
        (HEADER + "035437,market_wrap,YES,\n", "needs an email and a reason"),
        (HEADER + "035999,market_wrap,YES,a recap\n", "no email '035999' in the data"),
        ("035437,market_wrap,YES,a recap\n", "the first line must be email,field,value,reason"),
        (
            HEADER + "035437,market_wrap,YES,a recap\n035437,market_wrap,NO,on second thought\n",
            "035437 market_wrap is already corrected",
        ),
    ],
)
def test_a_mistake_in_the_file_stops_the_run(tmp_path, text, problem):
    with pytest.raises(ValueError, match=problem):
        load_reviewed(write(tmp_path, text), KNOWN)


def test_reviewed_wrap_gets_the_brief_tags_and_keeps_the_ai_answer():
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
        "Market wrap set to YES by a reviewer (the AI said NO): a weekly recap behind a link"
    ]
    # the contradiction is settled; the date has nothing to do with it and stays flagged
    assert [f.field for f in record.meta.flags] == ["date"]


def test_a_reviewed_title_replaces_the_label_the_ai_took():
    # 035347: the AI took the company line, the headline is below it
    email = prepared_email(body="Eli Lilly & Co. (LLY.N)\nMounjaro+Zepbound Script Tracker")
    reviewed = [Reviewed("folder_name", "Mounjaro+Zepbound Script Tracker", "the headline")]
    record = build_record(email, llm_output(title="Eli Lilly"), "model", "v4", reviewed)
    assert record.folder_name == "Mounjaro+Zepbound Script Tracker"
    assert record.meta.reviewed == [
        "Title set to Mounjaro+Zepbound Script Tracker by a reviewer (the AI said Eli Lilly): "
        "the headline"
    ]
    assert "title" not in [f.field for f in record.meta.flags]


def test_confirming_no_leaves_the_flags_it_does_not_settle():
    # companies without an Equity tag stay questionable when the reviewer keeps NO
    output = llm_output(
        primary_asset_tag="Thematics", asset_tags=["Thematics"], companies_mentioned=["Novo"]
    )
    record = build_record(
        prepared_email(), output, "model", "v2", [Reviewed("market_wrap", "NO", "x")]
    )
    assert "companies_mentioned" in [f.field for f in record.meta.flags]


def test_without_a_review_the_model_answer_stands():
    output = llm_output(primary_asset_tag="Market Wrap", asset_tags=["Market Wrap"])
    record = build_record(prepared_email(), output, "model", "v2")
    assert (record.market_wrap, record.meta.reviewed) == ("NO", [])
    assert "primary_asset_tag" in [f.field for f in record.meta.flags]
