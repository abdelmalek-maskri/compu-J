import json
import os

import litellm
import pytest
from fastapi.testclient import TestClient

from api.main import Config, create_app
from pipeline.llm_client import Settings
from rag.embed import Embedder, VectorStore
from rag.ingest import DOCUMENT
from tests.test_rag import chunk, fake_response

PASSAGES = [
    chunk("035241", "Brent crude should stay near USD 85 a barrel.", bank="Barclays"),
    chunk("035283", "Fed policy is more likely accommodative than restrictive."),
    chunk("035337", "We moderate our gold target to USD 5,800/oz."),
]
EMBEDDER = Embedder("test/fake")


def fake_embed(embedder, texts, task):
    """meaning reduced to two topics: energy, and everything else"""
    energy = ("oil", "crude", "brent", "petrol")
    return [[1.0, 0.0] if any(w in t.lower() for w in energy) else [0.0, 1.0] for t in texts]


def answer_json(**overrides) -> str:
    data = {
        "answered": True,
        "missing": "",
        "points": [
            {"claim": "Brent near 85", "source": 1, "quote": "stay near USD 85 a barrel"},
            {"claim": "Invented", "source": 1, "quote": "oil will double"},
        ],
    }
    return json.dumps({**data, **overrides})


def write_index(tmp_path, passages, with_vectors=True):
    path = tmp_path / "chunks.jsonl"
    path.write_text("".join(json.dumps(c.to_json()) + "\n" for c in passages))
    if with_vectors:
        store = VectorStore(EMBEDDER, root=tmp_path, call=fake_embed, log=lambda _: None)
        store.embed([c.embedded_text for c in passages], DOCUMENT)
    return path


def make_client(tmp_path, complete=None, chunks=None) -> TestClient:
    sent = []

    def fake_complete(settings, messages, schema):
        sent.append(messages)
        return fake_response(answer_json())

    config = Config(
        data_dir=tmp_path / "Data",
        deliverable=tmp_path / "classified_emails.json",
        details=tmp_path / "details.json",
        headlines=tmp_path / "headlines.json",
        rag_chunks=chunks or tmp_path / "chunks.jsonl",
        rag_root=tmp_path,
        embedder=EMBEDDER,
        embed_call=fake_embed,
        answer_settings=Settings.from_name("gemma"),
        answer_complete=complete or fake_complete,
    )
    client = TestClient(create_app(config))
    client.sent = sent
    return client


@pytest.fixture
def client(tmp_path):
    write_index(tmp_path, PASSAGES)
    return make_client(tmp_path)


def test_an_answer_comes_with_checked_points_and_its_sources(client):
    reply = client.post("/api/ask", json={"question": "What about petrol?"}).json()
    assert reply["answered"] is True
    assert [p["verified"] for p in reply["points"]] == [True, False]
    assert reply["points"][1]["problem"] == "the quote is not in source 1"
    first = reply["sources"][0]
    assert (first["n"], first["email_id"], first["bank"]) == (1, "035241", "Barclays")
    # found by meaning only: "petrol" is not in the passage
    assert (first["keyword_rank"], first["vector_rank"]) == (None, 1)
    assert "[1] Barclays | 2026-04-10" in client.sent[0][1]["content"]


def test_sources_only_never_calls_the_answer_model(client):
    reply = client.post(
        "/api/ask", json={"question": "gold target", "mode": "keyword", "sources_only": True}
    ).json()
    assert reply["answered"] is None and reply["points"] == []
    assert [s["email_id"] for s in reply["sources"]] == ["035337"]
    assert client.sent == []


def test_filters_narrow_the_search(client):
    reply = client.post(
        "/api/ask",
        json={"question": "policy outlook", "bank": "Barclays", "sources_only": True},
    ).json()
    assert {s["bank"] for s in reply["sources"]} == {"Barclays"}


def test_a_date_range_leaves_out_other_days(tmp_path):
    write_index(tmp_path, [*PASSAGES, chunk("035400", "Crude fell.", date="2026-04-13")])
    client = make_client(tmp_path)
    reply = client.post(
        "/api/ask",
        json={"question": "crude", "mode": "keyword", "since": "2026-04-13", "sources_only": True},
    ).json()
    assert [s["email_id"] for s in reply["sources"]] == ["035400"]


@pytest.mark.parametrize(
    "body",
    [{"question": "   "}, {"question": "x" * 501}, {"question": "oil", "mode": "magic"}, {}],
)
def test_a_bad_question_is_refused(client, body):
    assert client.post("/api/ask", json=body).status_code == 422


def test_no_index_says_how_to_build_it(tmp_path):
    response = make_client(tmp_path).post("/api/ask", json={"question": "oil"})
    assert response.status_code == 503
    assert "rag.ingest" in response.json()["detail"]


def test_missing_vectors_say_how_to_build_them(tmp_path):
    write_index(tmp_path, PASSAGES, with_vectors=False)
    client = make_client(tmp_path)
    response = client.post("/api/ask", json={"question": "oil"})
    assert response.status_code == 503 and "no vector yet" in response.json()["detail"]
    # keyword search needs no vectors
    keyword = client.post("/api/ask", json={"question": "oil", "mode": "keyword"})
    assert keyword.status_code == 200


def test_a_model_that_refuses_gives_429(tmp_path):
    write_index(tmp_path, PASSAGES)

    def refusing(settings, messages, schema):
        raise litellm.exceptions.AuthenticationError("bad key", "ollama", "gemma")

    response = make_client(tmp_path, complete=refusing).post("/api/ask", json={"question": "oil"})
    assert response.status_code == 429


def test_an_answer_that_breaks_the_schema_gives_502(tmp_path):
    write_index(tmp_path, PASSAGES)

    def broken(settings, messages, schema):
        return fake_response("not json")

    response = make_client(tmp_path, complete=broken).post("/api/ask", json={"question": "oil"})
    assert response.status_code == 502


def test_a_new_ingest_is_picked_up_without_a_restart(tmp_path):
    path = write_index(tmp_path, PASSAGES)
    client = make_client(tmp_path)
    body = {"question": "silver", "mode": "keyword", "sources_only": True}
    assert client.post("/api/ask", json=body).json()["sources"] == []
    write_index(tmp_path, [chunk("035500", "Silver rallied.")])
    os.utime(path, (1, 1))
    assert [s["email_id"] for s in client.post("/api/ask", json=body).json()["sources"]] == [
        "035500"
    ]


def test_the_dashboard_may_post_questions(client):
    preflight = client.options(
        "/api/ask",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert "POST" in preflight.headers["access-control-allow-methods"]
