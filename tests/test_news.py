import json
from datetime import UTC, datetime

import httpx
import pytest

import fetch_news
from news.headlines import (
    MIN_HEADLINES,
    Headline,
    SourceError,
    fetch_finnhub,
    fetch_once,
    load,
    parse_finnhub,
    parse_rss,
    save,
    tidy,
)

NOW = datetime(2026, 10, 25, 20, 30, tzinfo=UTC)


def article(n: int, **overrides) -> dict:
    return {
        "headline": f"Stocks move on story {n}",
        "url": f"https://www.cnbc.com/story-{n}.html",
        "source": "CNBC",
        "datetime": 1_761_400_000 + n,
        **overrides,
    }


def rss(*items: str) -> str:
    return f"<rss><channel><title>CNBC</title>{''.join(items)}</channel></rss>"


def item(n: int) -> str:
    return (
        f"<item><title>Oil &amp; gas story {n}</title><link>https://www.cnbc.com/oil-{n}.html</link>"
        f"<pubDate>Sat, 25 Oct 2026 1{n % 10}:00:00 GMT</pubDate></item>"
    )


class FakeGet:
    """plays back responses or errors, and records the requests"""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def ok_json(data) -> httpx.Response:
    return httpx.Response(200, json=data)


def test_finnhub_articles_become_headlines():
    [h] = parse_finnhub([article(1)])
    assert h == Headline(
        "Stocks move on story 1", "https://www.cnbc.com/story-1.html", "CNBC", h.published
    )
    assert h.published.startswith("2025-")


def test_only_plain_text_and_https_links_are_kept():
    data = [
        article(1, url="http://insecure.example.com/x"),
        article(2, url="javascript:alert(1)"),
        article(3, headline="   "),
        article(4, headline="  Spaced \n  out  "),
    ]
    assert [h.title for h in parse_finnhub(data)] == ["Spaced out"]


def test_rss_items_become_headlines_with_utc_times():
    [h] = parse_rss(rss(item(1)), "CNBC")
    assert (h.title, h.url, h.source) == (
        "Oil & gas story 1",
        "https://www.cnbc.com/oil-1.html",
        "CNBC",
    )
    assert h.published == "2026-10-25T11:00:00+00:00"


def test_broken_or_malicious_xml_is_refused():
    with pytest.raises(SourceError):
        parse_rss("<rss><channel>", "CNBC")
    bomb = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss>&a;</rss>'
    with pytest.raises(SourceError):
        parse_rss(bomb, "CNBC")


def test_the_key_is_sent_in_a_header_not_the_url():
    get = FakeGet(ok_json([article(1)]))
    fetch_finnhub("secret-key", get)
    url, headers = get.calls[0]
    assert "secret-key" not in url
    assert headers == {"X-Finnhub-Token": "secret-key"}


def test_network_errors_are_retried_but_a_refused_key_is_not():
    waits = []
    get = FakeGet(httpx.ConnectError("down"), httpx.Response(503), ok_json([article(1)]))
    assert len(fetch_finnhub("key", get, waits.append)) == 1
    assert waits == [2, 5]
    with pytest.raises(SourceError, match="check the API key"):
        fetch_finnhub("wrong", FakeGet(httpx.Response(401)), waits.append)
    with pytest.raises(SourceError, match="rate limited"):
        fetch_finnhub("key", FakeGet(httpx.Response(429)), waits.append)


def test_tidy_sorts_newest_first_and_removes_repeats():
    h = lambda title, url, t: Headline(title, url, "X", t)  # noqa: E731
    result = tidy(
        [
            h("Old story", "https://a.com/1", "2026-10-25T08:00:00+00:00"),
            h("New story", "https://a.com/2", "2026-10-25T10:00:00+00:00"),
            h("New story", "https://b.com/9", "2026-10-25T09:00:00+00:00"),  # same title elsewhere
            h("Repeat link", "https://a.com/1", "2026-10-25T07:00:00+00:00"),
        ]
    )
    assert [x.title for x in result] == ["New story", "Old story"]


def enough(prefix: str):
    return [Headline(f"{prefix} {i}", f"https://{prefix}.com/{i}", prefix, None) for i in range(6)]


def failing(message: str):
    def fetch():
        raise SourceError(message)

    return fetch


def test_the_first_working_source_wins():
    payload = fetch_once(
        [("finnhub", lambda: enough("fh")), ("rss:CNBC", lambda: enough("rss"))], None, NOW
    )
    assert (payload["source"], payload["stale"], payload["error"]) == ("finnhub", False, None)
    assert payload["last_updated"] == NOW.isoformat()


def test_the_backup_is_used_when_the_main_source_fails_or_returns_too_little():
    sources = [("finnhub", failing("rate limited (429)")), ("rss:CNBC", lambda: enough("rss"))]
    payload = fetch_once(sources, None, NOW)
    assert (payload["source"], payload["error"]) == ("rss:CNBC", "finnhub: rate limited (429)")
    too_few = [
        ("finnhub", lambda: enough("fh")[: MIN_HEADLINES - 1]),
        ("rss:CNBC", lambda: enough("rss")),
    ]
    assert fetch_once(too_few, None, NOW)["source"] == "rss:CNBC"


def test_when_everything_fails_the_last_good_headlines_are_kept_and_marked_stale():
    previous = fetch_once(
        [("finnhub", lambda: enough("fh"))], None, datetime(2026, 10, 25, 18, tzinfo=UTC)
    )
    payload = fetch_once([("finnhub", failing("could not connect"))], previous, NOW)
    assert payload["stale"] is True
    assert payload["headlines"] == previous["headlines"]
    assert payload["last_updated"] == previous["last_updated"]  # when they were really fetched
    assert payload["checked_at"] == NOW.isoformat()
    assert payload["error"] == "finnhub: could not connect"


def test_nothing_to_keep_gives_an_empty_stale_file():
    payload = fetch_once([("finnhub", failing("down"))], None, NOW)
    assert (payload["headlines"], payload["stale"], payload["last_updated"]) == ([], True, None)


def test_save_and_load(tmp_path):
    path = tmp_path / "headlines.json"
    payload = fetch_once([("finnhub", lambda: enough("fh"))], None, NOW)
    save(payload, path)
    assert load(path) == payload
    assert [p.name for p in tmp_path.iterdir()] == ["headlines.json"]
    path.write_text("{not json")
    assert load(path) is None
    assert load(tmp_path / "missing.json") is None


def test_the_command_uses_rss_without_a_key_and_saves_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr("fetch_news.load_dotenv", lambda: None)
    feed = rss(*(item(n) for n in range(8)))
    monkeypatch.setattr("news.headlines.http_get", FakeGet(httpx.Response(200, text=feed)))
    out = tmp_path / "headlines.json"
    monkeypatch.setattr("sys.argv", ["fetch_news.py", "--out", str(out)])
    assert fetch_news.main() == 0
    saved = json.loads(out.read_text())
    assert (saved["source"], saved["stale"], len(saved["headlines"])) == ("rss:CNBC", False, 8)
