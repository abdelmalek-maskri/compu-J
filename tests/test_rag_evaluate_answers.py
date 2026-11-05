import pytest

from pipeline.llm_client import LLMError, StopRun
from rag.answer import CheckedPoint
from rag.evaluate import Question
from rag.evaluate_answers import (
    COLUMNS,
    NO_POINTS,
    answer_all,
    check_labels,
    read_answers,
    report,
    rows_for,
    write_answers,
)
from rag.qa import Reply
from rag.search import Hit
from tests.test_rag import chunk

GOLD = Question("Gold target?", {"035337"}, "Deutsche Bank", None, "same")
CARTOON = Question("Cartoons about Iran?", {"035432"}, None, None, "picture", {"035432:3"})


def reply(*points: CheckedPoint) -> Reply:
    hits = [
        Hit(chunk("035337", "We moderate our gold target to USD 5,800/oz."), 1, 1),
        Hit(chunk("035432", "[cartoon] A tug of war", picture="cartoon", pdf="wac.pdf", page=3),
            2, 2),
    ]  # fmt: skip
    return Reply(hits, True, list(points), "")


def point(source=1, verified=True, from_picture=False, claim="Gold target cut to 5,800"):
    problem = None if verified else f"the quote is not in source {source}"
    return CheckedPoint(claim, source, "gold target to USD 5,800", verified, problem, from_picture)


def test_each_point_becomes_a_row_to_label():
    rows = rows_for(GOLD, reply(point(), point(2, False, True, "A cartoon")), "hybrid", "luna")
    assert [r["point"] for r in rows] == ["1", "2"]
    assert rows[0]["source"] == "[1] 035337 | Deutsche Bank | 2026-04-10 | email body"
    assert (
        rows[1]["source"] == "[2] 035432 | Deutsche Bank | 2026-04-10 | picture in wac.pdf, page 3"
    )
    assert (rows[1]["quote_found"], rows[1]["from_picture"]) == ("no", "yes")
    assert all(r["supported"] == "" and r["bank"] == "Deutsche Bank" for r in rows)


def test_a_question_left_unanswered_still_gets_a_row():
    [row] = rows_for(CARTOON, reply(), "hybrid", "luna")
    assert (row["point"], row["claim"]) == ("0", NO_POINTS)


def test_a_point_citing_a_missing_source_is_kept_to_label():
    [row] = rows_for(GOLD, reply(point(source=9, verified=False)), "hybrid", "luna")
    assert row["source"] == "[9] (no such source)"


def test_only_new_questions_are_answered_and_labels_are_kept(tmp_path):
    path = tmp_path / "answers.csv"
    labelled = rows_for(GOLD, reply(point()), "hybrid", "luna")
    labelled[0]["supported"] = "yes"
    write_answers(labelled, path)

    asked = []

    def ask(q):
        asked.append(q.text)
        return reply(point(2, True, True, "A tug of war cartoon"))

    rows, stopped = answer_all([GOLD, CARTOON], read_answers(path), ask, "hybrid", "luna",
                               log=lambda _: None)  # fmt: skip
    assert asked == ["Cartoons about Iran?"] and stopped is None
    write_answers(rows, path)
    again = read_answers(path)
    assert [r["supported"] for r in again] == ["yes", ""]


def test_a_failed_question_is_skipped_and_a_refusing_model_stops_keeping_the_rest():
    answers = iter([LLMError("bad"), reply(point()), StopRun("quota")])

    def ask(q):
        result = next(answers)
        if isinstance(result, Exception):
            raise result
        return result

    third = Question("Oil?", {"035241"}, None, None, "same")
    logs = []
    rows, stopped = answer_all([GOLD, CARTOON, third], [], ask, "hybrid", "luna", logs.append)
    assert "FAILED" in logs[0]
    assert [r["question"] for r in rows] == ["Cartoons about Iran?"]
    assert stopped == "quota"


def test_a_file_with_other_columns_is_refused(tmp_path):
    path = tmp_path / "answers.csv"
    path.write_text("question,claim\nGold?,cut\n")
    with pytest.raises(ValueError, match="columns"):
        read_answers(path)


def labelled_rows(*labels_and_checks) -> list[dict]:
    rows = []
    for n, (label, quote_found, group) in enumerate(labels_and_checks, 1):
        row = dict.fromkeys(COLUMNS, "")
        row.update(question=f"Q{n % 2}", point=str(n), supported=label, quote_found=quote_found,
                   wording=group, from_picture="yes" if group == "picture" else "no")  # fmt: skip
        rows.append(row)
    return rows


def test_labels_must_be_yes_partly_or_no():
    rows = labelled_rows(("yes", "yes", "same"), ("maybe", "yes", "same"), ("", "yes", "same"))
    [problem] = check_labels(rows)
    assert problem.startswith("row 3: 'maybe'")


def test_the_score_measures_the_quote_check_against_the_labels():
    rows = labelled_rows(
        ("yes", "yes", "same"),
        ("yes", "no", "same"),  # flagged, but a person found it supported
        ("no", "no", "picture"),  # caught
        ("partly", "yes", "picture"),  # let through: the quote is real but backs only part
        ("", "yes", "same"),  # not labelled yet
    )
    text = report(rows)
    assert (
        "5 points from 2 answered questions (0 said the passages do not answer them); 4 labelled"
        in text
    )
    assert "all: supported 50%, partly 25%, not 25% (4 points)" in text
    assert "  picture: supported 0%, partly 50%, not 50% (2 points)" in text
    assert "  citing a picture: supported 0%" in text
    assert "caught 1 of 2 points not fully supported, let 1 through, and flagged 1" in text


def test_the_score_says_what_to_do_before_any_label():
    assert "label the 'supported' column" in report(labelled_rows(("", "yes", "same")))
