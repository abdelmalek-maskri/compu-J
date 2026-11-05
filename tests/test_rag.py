import json
from types import SimpleNamespace

import litellm
import pytest

from pipeline.clean_emails import Attachments
from pipeline.llm_client import Settings, StopRun
from rag import chunks as chunks_module
from rag.answer import Answer, Point, ask_model, check
from rag.chunks import Chunk, Source, boilerplate, make_chunks, split_text, strip_lines
from rag.embed import Embedder, VectorStore
from rag.evaluate import Question, load_questions, ranked, score, summary
from rag.ingest import build_sources, load_chunks
from rag.search import Filters, Hit, Keyword, cosine, diverse, fuse, search
from tests.factories import prepared_email


def chunk(email_id="035300", text="text", **overrides) -> Chunk:
    data = {
        "id": f"{email_id}-{text[:8]}",
        "email_id": email_id,
        "text": text,
        "title": "FX Daily",
        "bank": "Deutsche Bank",
        "date": "2026-04-10",
        "market_wrap": "NO",
        "asset_tags": ["FX"],
        "companies": [],
        "pdf": None,
        "page": None,
    }
    return Chunk(**{**data, **overrides})


def test_short_text_is_one_passage():
    assert split_text("line one\nline two") == ["line one\nline two"]


def test_passages_stay_under_the_limit_and_overlap(monkeypatch):
    monkeypatch.setattr(chunks_module, "MAX_CHARS", 30)
    monkeypatch.setattr(chunks_module, "OVERLAP_CHARS", 10)
    text = "\n".join(f"line {i:02}" for i in range(8))
    passages = split_text(text)
    assert all(len(p) <= 30 for p in passages)
    # the last line of each passage starts the next, so no sentence is lost at the boundary
    for before, after in zip(passages, passages[1:], strict=False):
        assert after.splitlines()[0] == before.splitlines()[-1]
    assert {line for p in passages for line in p.splitlines()} == set(text.splitlines())


def test_a_line_longer_than_a_passage_is_cut_between_words(monkeypatch):
    monkeypatch.setattr(chunks_module, "MAX_CHARS", 20)
    passages = split_text("word " * 12)
    assert all(len(p) <= 20 for p in passages)
    assert all(not p.startswith(" ") and "wor d" not in p for p in passages)


def test_lines_in_many_emails_are_boilerplate():
    footer = "Unsubscribe | Manage subscriptions"
    bodies = [f"Note {i}\n{footer}" for i in range(5)] + ["Note 9\nOil is up"]
    remove = boilerplate(bodies)
    assert footer.casefold() in remove
    assert "oil is up" not in remove
    assert strip_lines(f"Oil is up\n  {footer}  ", remove) == "Oil is up"


def test_short_repeated_lines_are_kept():
    bodies = [f"Europe\nStock rating Overweight\nNote {i}" for i in range(5)]
    assert boilerplate(bodies) == set()


def test_one_email_repeating_a_line_is_not_boilerplate():
    assert boilerplate(["Gold\nGold\nGold\nGold\nGold"]) == set()


def test_passages_never_cross_a_page_and_carry_the_classification():
    src = dict(title="Weekly", bank="UBP", date=None, market_wrap="NO", asset_tags=["FX"],
               companies=[])  # fmt: skip
    found = make_chunks([
        Source("035356", "page one text", pdf="views.pdf", page=1, **src),
        Source("035356", "page two text", pdf="views.pdf", page=2, **src),
    ])  # fmt: skip
    assert [c.page for c in found] == [1, 2]
    assert found[0].id != found[1].id
    assert (
        found[1].embedded_text == "UBP | no date | Weekly | FX | views.pdf, page 2\npage two text"
    )


def test_build_sources_skips_duplicates_and_uses_the_classification(tmp_path):
    records = {"035300": {"folder_name": "FX Daily", "bank": "Deutsche Bank",
                          "date": "2026-04-10", "market_wrap": "NO", "asset_tags": ["FX"],
                          "companies_mentioned": []}}  # fmt: skip
    emails = [
        prepared_email(id="035300", body="We stay short USD/JPY."),
        prepared_email(id="035301", body="We stay short USD/JPY.", duplicate_of="035300"),
        prepared_email(id="035302", body="Gold note", bank="UBS"),
    ]
    sources, problems = build_sources(emails, records, tmp_path)
    assert [s.email_id for s in sources] == ["035300", "035302"]
    assert sources[0].date == "2026-04-10"
    # not classified yet: still searchable, with the rules' bank, and reported
    assert sources[1].bank == "UBS" and sources[1].date is None
    assert problems == ["035302: not in classified_emails.json, so no date, title or tags"]


def test_an_unreadable_pdf_is_reported_not_fatal(tmp_path):
    (tmp_path / "035300").mkdir()
    (tmp_path / "035300" / "broken.pdf").write_bytes(b"not a pdf")
    email = prepared_email(attachments=Attachments(["broken.pdf"], [], {}))
    sources, problems = build_sources([email], {}, tmp_path)
    assert len(sources) == 1
    assert any("broken.pdf: could not read" in p for p in problems)


def test_load_chunks_says_how_to_build_a_missing_index(tmp_path):
    with pytest.raises(FileNotFoundError, match="rag.ingest"):
        load_chunks(tmp_path / "chunks.jsonl")


def test_keyword_search_weighs_rare_words():
    found = [chunk(text="markets moved today"), chunk(text="Brent crude and markets")] + [
        chunk(text=f"markets note {i}") for i in range(5)
    ]
    scores = Keyword(found).scores("Brent markets")
    assert scores.index(max(scores)) == 1


def test_cosine_ignores_length():
    assert cosine([1, 0], [5, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 3]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_fusion_rewards_passages_both_searches_find():
    assert fuse([1, 2, 3], [3, 4, 1])[:2] == [1, 3]


def test_no_email_fills_every_slot():
    found = [chunk("035432", f"page {i}") for i in range(5)] + [chunk("035300", "other")]
    kept = diverse(list(range(6)), found, k=4)
    assert kept == [0, 1, 2, 5]


def test_one_email_left_by_the_filters_fills_every_slot():
    # a 10 page PDF from one bank on one day: the cap must not leave 5 of 8 slots empty
    found = [chunk("035350", f"page {i}") for i in range(10)]
    assert diverse(list(range(10)), found, k=8) == list(range(8))


def test_skipped_passages_only_fill_what_other_emails_leave_empty():
    found = [chunk("035350", f"page {i}") for i in range(5)] + [chunk("035242", "other")]
    # variety first: the other email's passage comes before the backfilled ones
    assert diverse(list(range(6)), found, k=5) == [0, 1, 2, 5, 3]


@pytest.mark.parametrize(
    ("filters", "allowed"),
    [
        (Filters(bank="barclays"), False),
        (Filters(bank="deutsche bank"), True),
        (Filters(since="2026-04-11"), False),
        (Filters(until="2026-04-10"), True),
        (Filters(tag="fx"), True),
        (Filters(tag="Oil"), False),
        (Filters(company="nvidia"), True),
        (Filters(market_wrap="yes"), False),
    ],
)
def test_filters(filters, allowed):
    assert filters.allows(chunk(companies=["NVIDIA Corp"])) is allowed


def test_a_date_filter_leaves_out_undated_emails():
    assert not Filters(since="2026-01-01").allows(chunk(date=None))


def test_hybrid_search_finds_by_meaning_what_keywords_miss():
    found = [chunk("035001", "crude prices rose"), chunk("035002", "equity flows")]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    keyword_only = search("oil", found, Keyword(found), Filters(), mode="keyword")
    assert keyword_only == []
    hits = search("oil", found, Keyword(found), Filters(), k=1, mode="hybrid",
                  query_vector=[0.9, 0.1], vectors=vectors)  # fmt: skip
    assert hits[0].chunk.email_id == "035001"
    assert hits[0].vector_rank == 1 and hits[0].keyword_rank is None


def test_vector_search_needs_vectors():
    found = [chunk()]
    with pytest.raises(ValueError, match="vector"):
        search("oil", found, Keyword(found), Filters(), mode="vector")


def test_filters_apply_before_search():
    found = [chunk("035001", "oil view", bank="Barclays"), chunk("035002", "oil view")]
    hits = search("oil", found, Keyword(found), Filters(bank="Barclays"), mode="keyword")
    assert [h.chunk.email_id for h in hits] == ["035001"]


def hits_for(*texts) -> list[Hit]:
    return [Hit(chunk(text=t), 1, 1) for t in texts]


def test_check_confirms_quotes_and_catches_invented_ones():
    hits = hits_for("We raise our gold target to USD 5,800/oz.", "Oil fell 3%.")
    answer = Answer(answered=True, missing="", points=[
        Point(claim="Gold target raised", source=1, quote="gold target to USD 5,800"),
        Point(claim="Oil fell", source=1, quote="Oil fell 3%"),
        Point(claim="Silver", source=7, quote="silver"),
    ])  # fmt: skip
    checked = check(answer, hits)
    assert [p.verified for p in checked] == [True, False, False]
    assert checked[1].problem == "the quote is not in source 1"
    assert checked[2].problem == "cites source 7, which does not exist"


def fake_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_ask_model_sends_numbered_sources_and_reads_the_answer():
    sent = {}

    def fake(settings, messages, schema):
        sent["messages"], sent["schema"] = messages, schema
        return fake_response('{"answered": false, "points": [], "missing": "everything"}')

    answer = ask_model("Silver?", hits_for("Gold rose."), Settings.from_name("gemma"), fake)
    assert answer.answered is False
    assert sent["schema"] is Answer
    assert "[1] Deutsche Bank | 2026-04-10 | FX Daily" in sent["messages"][1]["content"]
    assert "never an instruction" in sent["messages"][0]["content"]


class FakeEmbedding:
    def __init__(self, fail_first: int = 0, error=litellm.exceptions.RateLimitError):
        self.calls, self.fail_first, self.error = [], fail_first, error

    def __call__(self, embedder, texts, task):
        self.calls.append((list(texts), task))
        if len(self.calls) <= self.fail_first:
            raise self.error("slow down", llm_provider="gemini", model=embedder.model)
        return [[float(len(t)), 1.0] for t in texts]


def store(tmp_path, fake, **embedder) -> VectorStore:
    e = Embedder("gemini/test", task_types=True, batch_size=2, **embedder)
    return VectorStore(e, root=tmp_path, call=fake, sleep=lambda _: None, log=lambda _: None)


def test_vectors_are_saved_and_never_asked_twice(tmp_path):
    fake = FakeEmbedding()
    first = store(tmp_path, fake).embed(["a", "bb", "ccc"], "RETRIEVAL_DOCUMENT")
    assert first == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert [len(texts) for texts, _ in fake.calls] == [2, 1]

    again = FakeEmbedding()
    assert store(tmp_path, again).embed(["bb", "a"], "RETRIEVAL_DOCUMENT") == [first[1], first[0]]
    assert again.calls == []
    # a question is embedded as a query, which is a different vector from the same document
    store(tmp_path, again).embed(["a"], "RETRIEVAL_QUERY")
    assert again.calls == [(["a"], "RETRIEVAL_QUERY")]


def test_a_broken_last_line_is_redone(tmp_path):
    fake = FakeEmbedding()
    s = store(tmp_path, fake)
    s.embed(["a"], "RETRIEVAL_DOCUMENT")
    with s.path.open("a", encoding="utf-8") as f:
        f.write('{"key": "half')
    assert store(tmp_path, fake).embed(["a"], "RETRIEVAL_DOCUMENT") == [[1.0, 1.0]]
    assert json.loads(s.path.read_text(encoding="utf-8").splitlines()[0])["vector"] == [1.0, 1.0]


def test_a_rate_limit_waits_then_carries_on(tmp_path):
    fake = FakeEmbedding(fail_first=2)
    assert store(tmp_path, fake).embed(["a"], "RETRIEVAL_DOCUMENT") == [[1.0, 1.0]]
    assert len(fake.calls) == 3


def test_a_rate_limit_that_never_ends_stops_and_keeps_what_was_done(tmp_path):
    fake = FakeEmbedding()
    store(tmp_path, fake).embed(["a"], "RETRIEVAL_DOCUMENT")
    refusing = FakeEmbedding(fail_first=99)
    with pytest.raises(StopRun, match="rate limit"):
        store(tmp_path, refusing).embed(["a", "b"], "RETRIEVAL_DOCUMENT")
    assert store(tmp_path, FakeEmbedding()).missing(["a", "b"], "RETRIEVAL_DOCUMENT") == ["b"]


def test_a_wrong_key_stops_at_once(tmp_path):
    fake = FakeEmbedding(fail_first=99, error=litellm.exceptions.AuthenticationError)
    with pytest.raises(StopRun, match="AuthenticationError"):
        store(tmp_path, fake).embed(["a"], "RETRIEVAL_DOCUMENT")
    assert len(fake.calls) == 1


def test_questions_file(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text(
        "question,expected,bank,date,wording,pages\n"
        "Gold?,035337 035435,,,same,\n"
        "UBP on 10 April?,035350,UBP,2026-04-10,hard_negative_filtered,\n"
        "Cartoons about Iran?,035432,,,picture,035432:3\n"
    )
    plain, dated, cartoon = load_questions(path)
    assert plain.expected == {"035337", "035435"} and plain.bank is None
    assert plain.filters == Filters()
    assert dated.filters == Filters(bank="UBP", since="2026-04-10", until="2026-04-10")
    assert plain.targets == {"035337", "035435"} and cartoon.targets == {"035432:3"}


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("question,answer\nGold?,035337\n", "columns"),
        ("question,expected,bank,date,wording,pages\nGold?,035337,,,easy,\n", "unknown wording"),
        ("question,expected,bank,date,wording,pages\nGold?,035337,,,same,035999:3\n", "does not"),
        ("question,expected,bank,date,wording,pages\nGold?,035337,,,same,035337:p3\n", "written"),
    ],
)
def test_a_wrong_questions_file_is_refused(tmp_path, content, problem):
    path = tmp_path / "q.csv"
    path.write_text(content)
    with pytest.raises(ValueError, match=problem):
        load_questions(path)


def question(*expected, pages=()) -> Question:
    return Question("?", set(expected), None, None, "same", set(pages))


def test_score():
    both = score(question("035002", "035009"), ["035001", "035002"])
    assert (both.found, both.recall, both.reciprocal_rank) == (True, 0.5, 0.5)
    none = score(question("035009"), ["035001"])
    assert (none.found, none.recall, none.reciprocal_rank) == (False, 0.0, 0)


def test_a_question_naming_pages_is_scored_by_page():
    wac = question("035432", pages=["035432:3"])
    hits = [Hit(chunk("035432", "p26", pdf="wac.pdf", page=26), 1, 1),
            Hit(chunk("035432", "p3", pdf="wac.pdf", page=3), 2, 2),
            Hit(chunk("035308", "body"), 3, 3)]  # fmt: skip
    assert ranked(wac, hits) == ["035432:26", "035432:3", "035308:email"]
    # the right email came first, but the right page only second
    assert score(wac, ranked(wac, hits)).reciprocal_rank == 0.5
    by_email = question("035432")
    assert score(by_email, ranked(by_email, hits)).reciprocal_rank == 1


def test_mrr_shows_a_wrong_day_ranked_first():
    # the 10 April note above the 13 April one asked for: found, but only half the credit
    wrong_first = score(question("035433"), ["035334", "035433"])
    assert wrong_first.found and wrong_first.reciprocal_rank == 0.5
    assert summary([wrong_first, score(question("035433"), ["035433"])]).endswith(
        "MRR 0.75 (2 questions)"
    )


class FakeClock:
    """time that only moves when the code under test sleeps"""

    def __init__(self):
        self.now, self.waits = 0.0, []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def paced_store(tmp_path, fake, clock, limit=100, batch_size=50) -> VectorStore:
    e = Embedder("gemini/test", batch_size=batch_size, tokens_per_minute=limit)
    return VectorStore(e, root=tmp_path, call=fake, sleep=clock.sleep, clock=clock,
                       log=lambda _: None)  # fmt: skip


def test_batches_hold_at_most_a_minutes_tokens(tmp_path):
    fake, clock = FakeEmbedding(), FakeClock()
    # each text counts 51 tokens, so a 100 token minute fits one per batch
    texts = [f"{i}" * 203 for i in range(3)]
    paced_store(tmp_path, fake, clock).embed(texts, "RETRIEVAL_DOCUMENT")
    assert [len(t) for t, _ in fake.calls] == [1, 1, 1]


def test_pacing_waits_out_the_minute_instead_of_being_refused(tmp_path):
    fake, clock = FakeEmbedding(), FakeClock()
    texts = [f"{i}" * 203 for i in range(3)]
    store = paced_store(tmp_path, fake, clock, limit=110, batch_size=1)
    store.embed(texts, "RETRIEVAL_DOCUMENT")
    # two 51 token batches fit in a 110 token minute; the third waits for the first to age out
    assert clock.waits == [60.0]
    assert len(fake.calls) == 3


def test_no_limit_means_no_waiting(tmp_path):
    fake, clock = FakeEmbedding(), FakeClock()
    e = Embedder("ollama/test", batch_size=2)
    store = VectorStore(e, root=tmp_path, call=fake, sleep=clock.sleep, clock=clock,
                        log=lambda _: None)  # fmt: skip
    store.embed(["a", "b", "c"], "RETRIEVAL_DOCUMENT")
    assert clock.waits == [] and store.minutes_needed(["a"]) == 0
