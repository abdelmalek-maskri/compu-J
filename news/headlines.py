"""fetch financial headlines for the dashboard's ticker and keep the last good set

Finnhub's news API is the main source; a public RSS feed is the backup, so the ticker still
works when Finnhub is down or no key is set. Finviz was left out: it has no API and its terms
discourage automated access.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

FINNHUB_URL = "https://finnhub.io/api/v1/news?category=general"
RSS_FEEDS = {"CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html"}
# fewer than this from a source means its response is broken, not that the news stopped
MIN_HEADLINES = 5
MAX_HEADLINES = 30
MAX_TITLE_CHARS = 300
TIMEOUT_SECONDS = 10
RETRY_WAITS = (2, 5)
# some feeds refuse requests that do not look like a browser
USER_AGENT = "Mozilla/5.0 (research-dashboard headline fetcher)"


class SourceError(Exception):
    """this source gave nothing usable this time; the next source is tried"""


@dataclass(frozen=True)
class Headline:
    title: str
    url: str
    source: str
    published: str | None  # ISO time in UTC


Get = Callable[[str, dict], httpx.Response]


def http_get(url: str, headers: dict) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": USER_AGENT, **headers}, timeout=TIMEOUT_SECONDS)


def _get_with_retries(get: Get, url: str, headers: dict, sleep=time.sleep) -> httpx.Response:
    """retries network errors and server errors; a refusal (wrong key, rate limit) is final"""
    for wait in (*RETRY_WAITS, None):
        try:
            response = get(url, headers)
        except httpx.TransportError as e:
            if wait is None:
                raise SourceError(f"could not connect: {e}") from e
            sleep(wait)
            continue
        if response.status_code >= 500 and wait is not None:
            sleep(wait)
            continue
        if response.status_code == 401 or response.status_code == 403:
            raise SourceError(f"refused with {response.status_code}: check the API key")
        if response.status_code == 429:
            raise SourceError("rate limited (429): too many requests, try again later")
        if response.status_code != 200:
            raise SourceError(f"unexpected status {response.status_code}")
        return response
    raise AssertionError("unreachable: the loop returns or raises")


def _clean(title: str | None, url: str | None, source: str, published: str | None):
    """one headline as plain, trusted data, or None: the ticker shows text and https links only"""
    title = " ".join((title or "").split())[:MAX_TITLE_CHARS]
    url = (url or "").strip()
    if not title or not url.startswith("https://"):
        return None
    return Headline(title=title, url=url, source=source, published=published)


def parse_finnhub(data) -> list[Headline]:
    if not isinstance(data, list):
        raise SourceError(f"expected a list of articles, got {type(data).__name__}")
    headlines = []
    for item in data:
        if not isinstance(item, dict):
            continue
        stamp = item.get("datetime")
        published = (
            datetime.fromtimestamp(stamp, UTC).isoformat()
            if isinstance(stamp, int | float)
            else None
        )
        cleaned = _clean(
            item.get("headline"), item.get("url"), item.get("source") or "Finnhub", published
        )
        if cleaned:
            headlines.append(cleaned)
    return headlines


def parse_rss(xml_text: str, source: str) -> list[Headline]:
    try:
        root = ElementTree.fromstring(xml_text)
    except (ElementTree.ParseError, DefusedXmlException) as e:
        raise SourceError(f"not a readable RSS feed: {e}") from e
    headlines = []
    for item in root.iter("item"):
        published = None
        if date_text := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(date_text).astimezone(UTC).isoformat()
            except (TypeError, ValueError):
                published = None
        cleaned = _clean(item.findtext("title"), item.findtext("link"), source, published)
        if cleaned:
            headlines.append(cleaned)
    return headlines


def fetch_finnhub(api_key: str, get: Get = http_get, sleep=time.sleep) -> list[Headline]:
    # the key goes in a header, not the URL, so it never appears in logged URLs
    response = _get_with_retries(get, FINNHUB_URL, {"X-Finnhub-Token": api_key}, sleep)
    try:
        return parse_finnhub(response.json())
    except ValueError as e:
        raise SourceError(f"Finnhub did not return JSON: {e}") from e


def fetch_rss(name: str, url: str, get: Get = http_get, sleep=time.sleep) -> list[Headline]:
    return parse_rss(_get_with_retries(get, url, {}, sleep).text, name)


def tidy(headlines: list[Headline]) -> list[Headline]:
    """newest first, no story twice (same link, or the same title from another outlet)"""
    seen_urls, seen_titles, result = set(), set(), []
    for h in sorted(headlines, key=lambda h: h.published or "", reverse=True):
        title_key = h.title.casefold()
        if h.url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(h.url)
        seen_titles.add(title_key)
        result.append(h)
    return result[:MAX_HEADLINES]


def default_sources(get: Get | None = None) -> list[tuple[str, Callable[[], list[Headline]]]]:
    # looked up at call time, so tests can replace the network with a fake
    get = get or http_get
    sources = []
    if key := os.getenv("FINNHUB_API_KEY"):
        sources.append(("finnhub", lambda: fetch_finnhub(key, get)))
    for name, url in RSS_FEEDS.items():
        sources.append((f"rss:{name}", lambda name=name, url=url: fetch_rss(name, url, get)))
    return sources


def fetch_once(sources, previous: dict | None, now: datetime) -> dict:
    """the first source with enough headlines wins; if all fail, the last good set is kept
    and marked stale, so the ticker shows old news with a warning instead of nothing"""
    errors = []
    for name, fetch in sources:
        try:
            headlines = tidy(fetch())
        except SourceError as e:
            errors.append(f"{name}: {e}")
            continue
        if len(headlines) < MIN_HEADLINES:
            errors.append(f"{name}: only {len(headlines)} usable headlines")
            continue
        return {
            "last_updated": now.isoformat(),
            "checked_at": now.isoformat(),
            "source": name,
            "stale": False,
            # fresh news from the backup still says why the first choice failed
            "error": "; ".join(errors) or None,
            "headlines": [asdict(h) for h in headlines],
        }
    reason = "; ".join(errors) or "no news source configured"
    if previous and previous.get("headlines"):
        return {**previous, "checked_at": now.isoformat(), "stale": True, "error": reason}
    return {
        "last_updated": None,
        "checked_at": now.isoformat(),
        "source": None,
        "stale": True,
        "error": reason,
        "headlines": [],
    }


def load(path: Path) -> dict | None:
    """the last saved file, or None when there is none or it cannot be read"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # write then rename, so the dashboard never reads half a file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
