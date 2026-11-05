import pytest

from rag.question import banks_asked, picture_asked, read_question, search_as_read
from rag.search import Filters
from tests.test_ask_api import PASSAGES, make_client, write_index
from tests.test_rag import chunk, fake_response


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


KNOWN = ["Barclays", "Goldman Sachs", "J.P. Morgan", "UBS"]


@pytest.mark.parametrize(
    ("question", "banks"),
    [
        ("compare what barclays and goldman sachs said about rates", ["Barclays", "Goldman Sachs"]),
        ("JP Morgan vs UBS on gold", ["J.P. Morgan", "UBS"]),
        ("Tell me the views of all the banks on interest rates", sorted(KNOWN)),
        ("What does each bank expect?", sorted(KNOWN)),
        ("What is Barclays' view on oil?", []),
        ("What did the Bank of England say?", []),
        ("What do central banks expect?", []),
    ],
)
def test_the_banks_a_question_compares(question, banks):
    assert banks_asked(question, KNOWN) == banks


def searching(found: dict):
    """a fake search: the hits it returns depend only on the bank filter"""
    calls = []

    def run(filters, n):
        calls.append((filters.bank, n))
        return found.get(filters.bank, [])[:n]

    return run, calls


def test_a_comparison_searches_each_bank_and_says_which_found_nothing():
    found = {"Barclays": ["b1", "b2", "b3", "b4"], "Goldman Sachs": ["g1"]}
    run, calls = searching(found)
    hits, reading = search_as_read(
        "compare Barclays, Goldman Sachs and UBS", Filters(), 8, KNOWN, run
    )
    assert hits == ["b1", "b2", "b3", "g1"]
    assert calls == [("Barclays", 3), ("Goldman Sachs", 3), ("UBS", 3)]
    assert (reading.banks, reading.banks_without) == (["Barclays", "Goldman Sachs", "UBS"], ["UBS"])


def test_many_banks_get_fewer_passages_each():
    run, calls = searching({})
    search_as_read("what do all the banks think", Filters(), 8, KNOWN, run)
    assert {n for _, n in calls} == {2}


def test_a_bank_the_person_chose_is_not_split():
    run, calls = searching({"UBS": ["u1"]})
    hits, reading = search_as_read("Barclays vs Goldman Sachs", Filters(bank="UBS"), 8, KNOWN, run)
    assert (hits, reading.banks, calls) == (["u1"], [], [("UBS", 8)])


def test_a_comparison_answer_is_told_what_the_search_did(tmp_path):
    passages = [chunk("035303", "Barclays sees easing", bank="Barclays"),
                chunk("035299", "Goldman expects two Fed cuts", bank="Goldman Sachs")]  # fmt: skip
    write_index(
        tmp_path, [*passages, chunk("035400", "UBS on gold", bank="UBS", date="2026-04-01")]
    )
    sent = []

    def fake(settings, messages, schema):
        sent.append(messages[1]["content"])
        return fake_response('{"answered": true, "missing": "", "points": []}')

    client = make_client(tmp_path, complete=fake)
    question = "compare Barclays and Goldman Sachs and UBS on Fed"
    # UBS has a passage, but none from 10 April on, so its search finds nothing
    body = {"question": question, "mode": "keyword", "since": "2026-04-10"}
    reply = client.post("/api/ask", json=body).json()
    assert reply["banks_from_question"] == ["Barclays", "Goldman Sachs", "UBS"]
    assert reply["banks_without_passages"] == ["UBS"]
    assert "This compares Barclays, Goldman Sachs, UBS" in sent[0]
    assert "No passage was found for UBS" in sent[0]


def test_two_banks_share_the_usual_number_of_passages():
    run, calls = searching({})
    search_as_read("Barclays vs Goldman Sachs on rates", Filters(), 8, KNOWN, run)
    assert calls == [("Barclays", 4), ("Goldman Sachs", 4)]
