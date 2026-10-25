import os
from datetime import date, datetime
from pathlib import Path

import pytest

from pipeline.clean_emails import (
    MIMECAST_BANNER,
    build_llm_input,
    clean_html,
    could_be_published,
    find_bank,
    find_date,
    find_duplicates,
    list_files,
    prepare_all,
    received_date,
    select_pages,
    strip_banner,
)


def test_removes_scripts_styles_and_comments():
    html = """<html><head><style>p {color: red}</style></head><body>
    <script>let x = 1;</script><!-- tracking --><p>Rates rallied.</p></body></html>"""
    assert clean_html(html) == "Rates rallied."


def test_keeps_logo_alt_text_and_drops_pixels():
    html = '<img src="logo.png" alt="Deutsche Bank Logo"><img src="p.gif" width="1"><p>FX Daily</p>'
    assert clean_html(html) == "[image: Deutsche Bank Logo]\nFX Daily"


def test_table_rows_become_lines_with_cells_separated():
    html = """<table>
    <tr><td>CARLSBERG</td><td>Denmark</td><td>2.40%</td></tr>
    <tr><td>SHELL</td><td>UK</td><td>2.48%</td></tr>
    </table>"""
    assert clean_html(html) == "CARLSBERG | Denmark | 2.40%\nSHELL | UK | 2.48%"


def test_paragraphs_inside_data_cells_stay_on_one_row():
    html = """<table><tr>
    <td><p class="MsoNormal">Tenor</p></td><td><p class="MsoNormal">EUR swap rate</p></td>
    </tr><tr>
    <td><p class="MsoNormal">5y</p></td><td><p class="MsoNormal">2.77%</p></td>
    </tr></table>"""
    assert clean_html(html) == "Tenor | EUR swap rate\n5y | 2.77%"


def test_source_line_wrapping_is_not_a_paragraph_break():
    html = "<p>Macro\nat a Glance: Latest\nviews and forecasts</p>"
    assert clean_html(html) == "Macro at a Glance: Latest views and forecasts"


def test_nested_layout_tables_do_not_repeat_text():
    html = """<table><tr><td>
    <table><tr><td>Macro at a Glance</td></tr></table>
    </td></tr></table>"""
    assert clean_html(html) == "Macro at a Glance"


def test_paragraphs_and_line_breaks_stay_separate():
    html = "<p>First point.</p><p>Second<br>third.</p>"
    assert clean_html(html) == "First point.\nSecond\nthird."


def test_links_keep_text_only():
    html = '<p>Read the <a href="https://research.db.com/x?id=123">full report</a>.</p>'
    assert clean_html(html) == "Read the full report."


def test_hidden_preheader_and_invisible_chars_removed():
    html = """<div style="display:none; max-height:0">Preview text&zwnj;&zwnj;</div>
    <p>Visible&zwnj; body</p>"""
    assert clean_html(html) == "Visible body"


def test_repeated_identical_lines_collapse():
    html = "<p>Disclaimer</p><p>Disclaimer</p><p>Body</p>"
    assert clean_html(html) == "Disclaimer\nBody"


def test_strip_banner_removes_only_the_banner():
    text = f"{MIMECAST_BANNER}\nRefs :\nLevels as of 07-Apr-26"
    assert strip_banner(text) == "Refs :\nLevels as of 07-Apr-26"


def test_list_files_finds_pdfs_images_and_thumbnails(tmp_path):
    (tmp_path / "inline").mkdir()
    (tmp_path / "thumbs").mkdir()
    for name in ["emailbody.html", "Flyer.pdf", "image001.jpg", "inline/image002.png"]:
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "thumbs" / "Flyer.pdf.png").write_bytes(b"")

    files = list_files(tmp_path)

    assert files.pdfs == ["Flyer.pdf"]
    assert files.images == ["image001.jpg", "inline/image002.png"]
    assert files.thumbnails == {"Flyer.pdf": "thumbs/Flyer.pdf.png"}


def test_bank_from_logo_beats_other_names_in_text():
    text = "[image: Goldman Sachs Research]\nWe compare our view with Barclays."
    assert find_bank(text) == ("Goldman Sachs", "logo")


def test_bank_earliest_mention_wins_in_top_text():
    text = "Morgan Stanley Research\nSee also J.P. Morgan's note."
    assert find_bank(text) == ("Morgan Stanley", "top_text")


def test_bank_from_signature_with_damaged_accent():
    lines = ["Dear Client,", "Please find attached our report."] + ["..."] * 40
    text = "\n".join([*lines, "Best regards, Union Bancaire Priv\ufffde, UBP SA"])
    assert find_bank(text) == ("UBP", "signature")


def test_bank_none_when_not_found():
    assert find_bank("Dear all,\nPlease find below.") == (None, None)


def test_date_formats_in_text():
    assert find_date("9 April 2026 | 4:48PM EDT", []) == (date(2026, 4, 9), "text")
    assert find_date("Levels as of 07-Apr-26 09:32 GMT", []) == (date(2026, 4, 7), "text")
    assert find_date("Published April 10, 2026", []) == (date(2026, 4, 10), "text")
    assert find_date("report as of 31.03.2026", []) == (date(2026, 3, 31), "text")


def test_date_earliest_in_text_wins():
    text = "9 April 2026\nMonday, 21 September 2026 investor trip"
    assert find_date(text, []) == (date(2026, 4, 9), "text")


def test_impossible_and_ambiguous_dates_are_skipped():
    assert find_date("31.02.2026 and 04/10/2026", []) == (None, None)


def test_date_falls_back_to_pdf_names():
    pdfs = ["DailyTechIndex_20260409_en.pdf"]
    assert find_date("Dear Client,", pdfs) == (date(2026, 4, 9), "pdf_name")
    assert find_date("Dear Client,", ["Daily Market Insights 09.04.2026.pdf"]) == (
        date(2026, 4, 9),
        "pdf_name",
    )


def test_select_pages_keeps_title_page_and_skips_short_pages_after_it():
    title = "WEEKLY ADVISORY CALL 13 April 2026"
    body = "US markets: if the rise continues, the index will test resistance. " * 5
    assert select_pages([title, "9", body, ""], budget=1000) == f"{title}\n\n{body.strip()}"


def test_select_pages_stops_at_budget_and_says_so():
    pages = ["a" * 300, "b" * 300, "c" * 300]
    result = select_pages(pages, budget=450)
    assert result == "a" * 300 + "\n\n" + "b" * 150 + " [truncated]"
    assert "ccc" not in result


def test_select_pages_tidies_whitespace():
    page = "Intraday   FX View\n\n\n  EUR/USD\t1.1658 " + "x" * 200
    assert select_pages([page], budget=1000).startswith("Intraday FX View\nEUR/USD 1.1658")


def test_llm_input_has_named_sections():
    result = build_llm_input("FX Daily", ["Intraday.pdf"], {"Intraday.pdf": "EUR/USD 1.1658"})
    assert result == (
        "EMAIL BODY:\nFX Daily\n\n"
        "ATTACHMENTS: Intraday.pdf\n\n"
        "PDF TEXT (Intraday.pdf):\nEUR/USD 1.1658"
    )


def test_llm_input_without_attachments():
    assert build_llm_input("Rates rallied.", [], {}) == (
        "EMAIL BODY:\nRates rallied.\n\nATTACHMENTS: none"
    )


def test_llm_input_lists_unreadable_pdf_without_text():
    result = build_llm_input("See attached.", ["broken.pdf"], {"broken.pdf": ""})
    assert result == "EMAIL BODY:\nSee attached.\n\nATTACHMENTS: broken.pdf"


def test_duplicates_point_to_first_copy_ignoring_whitespace():
    texts = {
        "035428": "UBS House View\nAffording a war",
        "035427": "UBS House View Affording  a war",
    }
    assert find_duplicates(texts) == {"035428": "035427"}


def test_different_emails_are_not_duplicates():
    assert find_duplicates({"a": "FX Daily 9 April", "b": "FX Daily 10 April"}) == {}


def test_date_after_arrival_is_rejected():
    text = "Subscription period until: 17.04.2026, 15:00 Geneva time"
    assert find_date(text, [], received=date(2026, 4, 9)) == (None, None)


def test_rejected_date_falls_through_to_the_next_one():
    text = "Webinar: Wednesday, 15 April 2026\nPublished 9 April 2026"
    assert find_date(text, [], received=date(2026, 4, 10)) == (date(2026, 4, 9), "text")


def test_one_day_after_arrival_is_allowed_for_time_zones():
    assert find_date("10 April 2026 | 9:00 HKT", [], received=date(2026, 4, 9)) == (
        date(2026, 4, 10),
        "text",
    )


def test_received_date_ignores_the_rewritten_email_body(tmp_path):
    (tmp_path / "inline").mkdir()
    body, image = tmp_path / "emailbody.html", tmp_path / "inline" / "image001.png"
    body.write_bytes(b"")
    image.write_bytes(b"")
    os.utime(body, (datetime(2026, 5, 26).timestamp(),) * 2)
    os.utime(image, (datetime(2026, 4, 9, 19).timestamp(),) * 2)
    assert received_date(tmp_path) == date(2026, 4, 9)


def test_received_date_is_none_without_attachments(tmp_path):
    (tmp_path / "emailbody.html").write_bytes(b"")
    assert received_date(tmp_path) is None


def make_email(folder, html: bytes, pdfs: dict[str, bytes] | None = None):
    folder.mkdir()
    (folder / "emailbody.html").write_bytes(html)
    for name, content in (pdfs or {}).items():
        (folder / name).write_bytes(content)


def test_prepare_all_runs_every_step(tmp_path):
    html = b'<img alt="Barclays"><p>9 April 2026</p><p>EU MedTech Investor Trip</p>'
    make_email(tmp_path / "035239", html)

    emails, failures = prepare_all(tmp_path)

    assert failures == {}
    [email] = emails
    assert (email.id, email.bank, email.bank_source) == ("035239", "Barclays", "logo")
    assert (email.date, email.date_source) == (date(2026, 4, 9), "text")
    assert email.llm_input.startswith("EMAIL BODY:\n[image: Barclays]")


def test_prepare_all_records_failures_and_continues(tmp_path):
    make_email(tmp_path / "good", b"<p>Rates rallied.</p>")
    (tmp_path / "empty").mkdir()
    (tmp_path / ".DS_Store").write_bytes(b"")

    emails, failures = prepare_all(tmp_path)

    assert [e.id for e in emails] == ["good"]
    assert list(failures) == ["empty"]
    assert failures["empty"].startswith("FileNotFoundError")


def test_windows_1252_file_is_decoded(tmp_path):
    make_email(tmp_path / "035432", b"<p>\xa9 Julius Baer Group</p>")
    [email], _ = prepare_all(tmp_path)
    assert email.encoding == "cp1252"
    assert email.body == "\u00a9 Julius Baer Group"


def test_broken_pdf_becomes_a_warning_not_a_failure(tmp_path):
    make_email(tmp_path / "035242", b"<p>See attached.</p>", {"report.pdf": b"not a pdf"})
    [email], failures = prepare_all(tmp_path)
    assert failures == {}
    assert email.warnings[0].startswith("could not read report.pdf")
    assert email.llm_input.endswith("ATTACHMENTS: report.pdf")


def test_prepare_all_flags_duplicates(tmp_path):
    for folder in ["035427", "035428"]:
        make_email(tmp_path / folder, b"<p>UBS House View: Affording a war</p>")
    emails, _ = prepare_all(tmp_path)
    assert [e.duplicate_of for e in emails] == [None, "035427"]


DATA = Path(__file__).parent.parent / "Data"


@pytest.mark.skipif(not DATA.is_dir(), reason="licensed data is not in the repository")
def test_real_data_prepares_cleanly():
    emails, failures = prepare_all(DATA)
    assert failures == {}
    assert len(emails) == 200
    assert all(e.bank for e in emails)
    # 184 found, minus a subscription deadline (035243) and an event (035341) dated after arrival
    assert sum(e.date is not None for e in emails) == 182
    assert all(could_be_published(e.date, e.received) for e in emails if e.date)
    assert [e.id for e in emails if e.duplicate_of] == ["035428"]
