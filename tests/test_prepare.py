from pipeline.prepare import (
    MIMECAST_BANNER,
    clean_html,
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
