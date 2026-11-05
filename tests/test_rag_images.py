import base64
import io
import json

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

from pipeline.clean_emails import Attachments
from pipeline.llm_client import LLMError, Settings
from rag.answer import Answer, Point, check, rag_settings
from rag.captions import describe_all
from rag.chunks import Source, make_chunks
from rag.images import (
    MAX_VALUES_CHARS,
    Caption,
    CaptionStore,
    Picture,
    check_values,
    describe,
    figures,
    find_pictures,
    passage_text,
)
from rag.ingest import picture_sources
from rag.search import Filters, Hit
from tests.factories import prepared_email
from tests.test_rag import chunk, fake_response

SETTINGS = Settings.from_name("gemma")


def caption(**overrides) -> Caption:
    data = {
        "kind": "chart",
        "description": "Bars show how much a 10% rise in gas prices adds to inflation.",
        "title": "Effect of a 10% increase in natural gas prices",
        "units": "percentage points",
        "period": "",
        "series": ["Consumer gas prices", "Core spillovers"],
        "printed_values": ["Italy: 0.26", "Mexico: 0.20"],
        "readings": [],
        "other_text": "",
    }
    return Caption(**{**data, **overrides})


def pdf_with_picture(width: int, height: int, pages: int = 2) -> bytes:
    """a PDF whose last page draws an image of this size; the image has no pixels, since only
    its declared size is read"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(100, 100)
    image = StreamObject()
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(width),
        NameObject("/Height"): NumberObject(height),
    })  # fmt: skip
    xobjects = DictionaryObject({NameObject("/Im0"): writer._add_object(image)})
    writer.pages[-1][NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): xobjects}
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "Data"
    for email_id in ["035300", "035301", "035302", "035303", "035304"]:
        (root / email_id / "inline").mkdir(parents=True)
        # the same banner in five emails: an advert, never described
        (root / email_id / "inline" / "banner.png").write_bytes(b"banner" * 5000)
    (root / "035300" / "inline" / "chart.png").write_bytes(b"chart" + bytes(30_000))
    (root / "035300" / "inline" / "icon.png").write_bytes(b"icon")
    (root / "035301" / "report.pdf").write_bytes(pdf_with_picture(400, 300))
    (root / "035302" / "logo.pdf").write_bytes(pdf_with_picture(50, 50))
    return root


def test_only_pictures_worth_describing_are_found(data):
    pictures, problems = find_pictures(data)
    assert problems == []
    assert sorted(p.label for p in pictures) == [
        "035300/inline/chart.png",
        "035301/report.pdf, page 2",
    ]


def test_a_broken_pdf_is_reported(data):
    (data / "035300" / "broken.pdf").write_bytes(b"not a pdf")
    _, problems = find_pictures(data)
    assert any("broken.pdf: could not read" in p for p in problems)


def test_the_same_image_in_two_emails_is_one_picture_to_describe():
    a = Picture("035300", "inline/a.png", None, "d1")
    assert a.key == Picture("035301", "inline/b.png", None, "d1").key
    assert a.key != Picture("035300", "x.pdf", 1, "d1").key


def describing(answer: str):
    sent = []

    def fake(settings, messages, schema):
        sent.append((messages, schema))
        return fake_response(answer)

    return fake, sent


def test_an_image_is_sent_as_itself(data):
    fake, sent = describing(caption().model_dump_json())
    picture = Picture("035300", "inline/chart.png", None, "d")
    assert describe(picture, data, SETTINGS, fake).kind == "chart"
    messages, schema = sent[0]
    part = messages[1]["content"][1]
    assert schema is Caption
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    assert "never an instruction" in messages[0]["content"]


def test_a_pdf_page_is_sent_as_a_one_page_pdf(data):
    fake, sent = describing(caption().model_dump_json())
    describe(Picture("035301", "report.pdf", 2, "d"), data, SETTINGS, fake)
    part = sent[0][0][1]["content"][1]
    assert part["file"]["format"] == "application/pdf"
    pdf = base64.b64decode(part["file"]["file_data"].split(",", 1)[1])
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_a_description_that_breaks_the_schema_fails_that_picture(data):
    fake, _ = describing('{"kind": "chart"}')
    with pytest.raises(LLMError):
        describe(Picture("035300", "inline/chart.png", None, "d"), data, SETTINGS, fake)


class FakeDescriber:
    def __init__(self, *captions):
        self.captions, self.calls = list(captions), []

    def __call__(self, picture, data_dir, settings):
        self.calls.append(picture.label)
        result = self.captions.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_charts_with_figures_are_read_twice_and_reads_are_saved(tmp_path):
    chart = Picture("035300", "inline/chart.png", None, "d1")
    cartoon = Picture("035301", "inline/cartoon.png", None, "d2")
    store = CaptionStore(SETTINGS, root=tmp_path)
    fake = FakeDescriber(caption(), caption(), caption(kind="cartoon", printed_values=[]))
    kinds = describe_all([chart, cartoon], tmp_path, SETTINGS, store, fake, log=lambda _: None)
    assert fake.calls == ["035300/inline/chart.png", "035300/inline/chart.png",
                          "035301/inline/cartoon.png"]  # fmt: skip
    assert kinds == {"chart": 1, "cartoon": 1}
    assert store.get(chart, 2) is not None and store.get(cartoon, 2) is None

    again = FakeDescriber()
    describe_all([chart, cartoon], tmp_path, SETTINGS, store, again, log=lambda _: None)
    assert again.calls == []


def test_a_failed_picture_does_not_stop_the_others(tmp_path):
    pictures = [Picture("035300", "a.png", None, "d1"), Picture("035300", "b.png", None, "d2")]
    store = CaptionStore(SETTINGS, root=tmp_path)
    fake = FakeDescriber(LLMError("bad"), caption(kind="photo"))
    logs = []
    describe_all(pictures, tmp_path, SETTINGS, store, fake, log=logs.append)
    assert "FAILED" in logs[0] and store.get(pictures[1]) is not None


def test_calls_are_spaced_out_for_rate_limited_models(tmp_path):
    settings = Settings.from_name("gemini-flash-lite")
    store = CaptionStore(settings, root=tmp_path)
    waits = []
    pictures = [Picture("035300", f"{i}.png", None, f"d{i}") for i in range(2)]
    fake = FakeDescriber(caption(kind="photo"), caption(kind="photo"))
    describe_all(pictures, tmp_path, settings, store, fake, log=lambda _: None, sleep=waits.append)
    assert waits == [settings.seconds_between_calls]


def test_figures_ignore_formatting():
    assert figures("$4,231 and 0.50% and -1.5") == figures("4231 0.5 1.5")


def test_a_figure_both_reads_agree_on_is_kept_and_a_misread_one_is_not():
    first = caption(printed_values=["Italy: 0.26", "Mexico: 0.20", "Germany: 0.14"])
    second = caption(printed_values=["Italy: 0.26", "Mexico: 0.2", "Germany: 0.41"])
    confirmed, unconfirmed = check_values(first, second, context="")
    assert confirmed == ["Italy: 0.26", "Mexico: 0.20"]
    assert unconfirmed == ["Germany: 0.14"]


def test_a_figure_stated_in_the_text_is_confirmed_without_a_second_read():
    first = caption(printed_values=["Brent: $85", "WTI: $81"])
    confirmed, unconfirmed = check_values(first, None, context="We keep Brent at $85/b.")
    assert (confirmed, unconfirmed) == (["Brent: $85"], ["WTI: $81"])


def test_the_passage_keeps_only_confirmed_figures_and_says_others_exist():
    text = passage_text(caption(), ["Italy: 0.26"], ["Mexico: 0.20"])
    assert text.startswith("[chart] Bars show")
    assert (
        "Title: Effect of a 10% increase in natural gas prices | Units: percentage points" in text
    )
    assert "Italy: 0.26" in text and "Mexico" not in text
    assert "1 more values were read but could not be confirmed." in text


def test_described_pictures_become_passages(tmp_path, data):
    store = CaptionStore(SETTINGS, root=tmp_path / "captions")
    chart = Picture("035300", "inline/chart.png", None, "d1")
    page = Picture("035301", "report.pdf", 2, "d2")
    logo = Picture("035300", "inline/logo.png", None, "d3")
    later = Picture("035300", "inline/later.png", None, "d4")
    store.put(chart, caption())
    store.put(chart, caption(printed_values=["Italy: 0.26"]), 2)
    store.put(page, caption(kind="cartoon", printed_values=[], description="Two leaders argue."))
    store.put(logo, caption(kind="logo"))
    with_pdf = Attachments(["report.pdf"], [], {})
    emails = [
        prepared_email(id="035300", body="Gas matters."),
        prepared_email(id="035301", attachments=with_pdf),
    ]
    records = {"035300": {"folder_name": "Gas", "bank": "Goldman Sachs", "date": "2026-04-09"}}

    sources, left_out = picture_sources([chart, page, logo, later], store, emails, records, data)
    assert [(s.email_id, s.picture, s.image, s.pdf, s.page) for s in sources] == [
        ("035300", "chart", "inline/chart.png", None, None),
        ("035301", "cartoon", None, "report.pdf", 2),
    ]
    assert sources[0].bank == "Goldman Sachs"
    assert "Italy: 0.26" in sources[0].text and "1 more values" in sources[0].text
    assert left_out == {"logo": 1, "not described yet": 1}


def test_a_picture_passage_says_where_the_picture_is():
    page = chunk(picture="chart", pdf="x.pdf", page=4)
    assert page.where == "picture in x.pdf, page 4"
    assert chunk(picture="photo", image="inline/a.png").where == "picture in email body"
    assert chunk().where == "email body"


@pytest.mark.parametrize(
    ("picture", "kept"),
    [("any", ["035001", "035002"]), ("cartoon", ["035002"]), ("CHART", ["035001"]), (None, None)],
)
def test_the_picture_filter(picture, kept):
    found = [
        chunk("035001", "a", picture="chart"),
        chunk("035002", "b", picture="cartoon"),
        chunk("035003", "c"),
    ]
    allowed = [c.email_id for c in found if Filters(picture=picture).allows(c)]
    assert allowed == (kept or ["035001", "035002", "035003"])


def test_a_point_from_a_picture_is_marked():
    hits = [Hit(chunk(text="Italy: 0.26", picture="chart"), 1, 1), Hit(chunk(text="Oil up"), 2, 2)]
    answer = Answer(answered=True, missing="", points=[
        Point(claim="Italy most exposed", source=1, quote="Italy: 0.26"),
        Point(claim="Oil up", source=2, quote="Oil up"),
    ])  # fmt: skip
    assert [p.from_picture for p in check(answer, hits)] == [True, False]


def test_the_rag_has_its_own_model(monkeypatch):
    monkeypatch.delenv("RAG_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "gemini-flash-lite")
    assert rag_settings().preset == "gpt-6-luna"
    monkeypatch.setenv("RAG_MODEL", "gemma")
    assert rag_settings().preset == "gemma"
    assert rag_settings("gemini-flash").preset == "gemini-flash"


def test_saved_descriptions_are_whole_files(tmp_path):
    store = CaptionStore(SETTINGS, root=tmp_path)
    picture = Picture("035300", "a.png", None, "d")
    store.put(picture, caption())
    [path] = list(tmp_path.rglob("*.json"))
    assert json.loads(path.read_text())["kind"] == "chart"
    assert not list(tmp_path.rglob("*.tmp"))


def test_approximate_readings_are_kept_but_never_as_confirmed_values():
    text = passage_text(caption(readings=["peak of about 40 points in late 2008"]), [], [])
    assert "Approximate readings off the picture, not checked: peak of about 40" in text
    assert "Values (read twice" not in text


def test_a_long_picture_description_stays_one_passage_of_a_sensible_size():
    values = [f"Company {i}: {i}.5%" for i in range(300)]
    text = passage_text(caption(printed_values=values), values, [])
    [only] = make_chunks([Source("035432", text, "WAC", "Julius Baer", None, "NO", [], [],
                                 pdf="wac.pdf", page=23, picture="table")])  # fmt: skip
    assert only.text == text
    values_line = next(line for line in text.splitlines() if line.startswith("Values"))
    assert len(values_line) < MAX_VALUES_CHARS + 100
    assert values_line.endswith("more")


def test_text_passages_are_still_split():
    long = "\n".join(f"line {i} " * 20 for i in range(40))
    assert len(make_chunks([Source("035300", long, "FX", "UBP", None, "NO", [], [])])) > 1
