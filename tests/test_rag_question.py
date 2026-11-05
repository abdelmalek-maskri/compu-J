import pytest

from rag.question import picture_asked, read_question
from rag.search import Filters
from tests.test_ask_api import PASSAGES, make_client, write_index
from tests.test_rag import chunk


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("Can you show me any funny cartoons with Khamenei?", "cartoon"),
        ("Is there a chart of S&P 500 volatility?", "chart"),
        ("Any graphs on gas prices?", "chart"),
        ("Show me pictures of the Strait", "any"),
        ("A cartoon or a chart about oil", "any"),
        ("What is on the table for the Fed?", None),
        ("What is Barclays' view on oil?", None),
    ],
)
def test_the_kind_of_picture_a_question_names(question, kind):
    assert picture_asked(question) == kind


def test_a_picture_filter_the_person_chose_is_kept():
    chosen = Filters(picture="chart")
    assert read_question("funny cartoons", chosen) == (chosen, None)
    assert read_question("funny cartoons", Filters(bank="UBS")) == (
        Filters(bank="UBS", picture="cartoon"),
        "cartoon",
    )


CARTOON = chunk("035432", "[cartoon] Trump and an Iranian leader in a tug of war over Iran",
                picture="cartoon", pdf="wac.pdf", page=3)  # fmt: skip
IRAN = [chunk(f"0353{n:02}", f"Iran war: cartoons of the conflict, part {n}") for n in range(5)]


def ask(client, **body):
    return client.post("/api/ask", json={"mode": "keyword", "sources_only": True, **body}).json()


def test_a_question_about_cartoons_searches_cartoons_and_says_so(tmp_path):
    write_index(tmp_path, [*IRAN, CARTOON])
    client = make_client(tmp_path)
    reply = ask(client, question="cartoons about Iran")
    assert [s["email_id"] for s in reply["sources"]] == ["035432"]
    assert reply["picture_from_question"] == "cartoon"
    # undone: every passage is searched again
    everything = ask(client, question="cartoons about Iran", read_question=False)
    assert everything["picture_from_question"] is None
    assert len(everything["sources"]) > 1


def test_when_no_picture_matches_everything_is_searched(tmp_path):
    write_index(tmp_path, PASSAGES)
    reply = ask(make_client(tmp_path), question="a chart of the gold target")
    assert reply["picture_from_question"] is None
    assert reply["sources"][0]["email_id"] == "035337"
