from datetime import date

from pipeline.check_metadata import appears_in, check_metadata
from tests.factories import llm_output, prepared_email

# 035243: the product is "issued by Goldman Sachs", the email is signed by UBP
UBP_FLYER = (
    "Structured Product Investment Proposal\n15 months tenor in USD, issued by Goldman Sachs\n"
    "Best regards, Union Bancaire Privee, UBP SA"
)


def test_text_matches_despite_spacing_case_and_curly_quotes():
    text = f"UBS House View {chr(0x201C)}Affording{chr(0xA0)}a war{chr(0x201D)} {chr(0x2013)} April"
    assert appears_in('ubs house view "affording a war" - april', text)
    assert not appears_in("UBS House View: Driving fuel demand", text)
    assert not appears_in("", text)


def test_export_damage_and_retyped_punctuation_do_not_count():
    # 035437: the export replaced the curly apostrophe with the replacement sign
    damaged = f"aims to summarise the previous week{chr(0xFFFD)}s major events"
    assert appears_in("the previous week's major events", damaged)
    assert appears_in(f"the previous week{chr(0x2019)}s major events", damaged)
    assert appears_in("Previous weeks major events", damaged)


def test_a_lost_apostrophe_matches_however_the_model_writes_it():
    # 035372: the email has "Europe\ufffds", the model wrote "Europes"
    email = "This week's most read research Equities \ufffd Europe\ufffds top ten"
    assert appears_in("This week's most read research Equities  Europes top ten", email)
    assert appears_in("Equities - Europe's top ten", email)
    assert appears_in(f"Europe{chr(0x2019)}s top ten", email)


def test_whole_words_only_and_punctuation_alone_never_matches():
    assert appears_in("FX Daily", "Today: FX Daily, 9 April")
    assert not appears_in("FX", "AFX Daily")
    assert not appears_in("!!!", "Today: FX Daily")


def test_title_is_the_models_and_marked_when_not_in_the_email():
    meta = check_metadata(prepared_email(), llm_output(title="Weekly FX Outlook"))
    assert (meta.title, meta.title_verified) == ("Weekly FX Outlook", False)
    assert check_metadata(prepared_email(), llm_output()).title_verified


def test_bank_agreement():
    meta = check_metadata(prepared_email(), llm_output(bank="Deutsche Bank"))
    assert (meta.bank, meta.bank_source) == ("Deutsche Bank", "llm+python")


def test_model_bank_wins_when_the_email_names_it():
    email = prepared_email(body=UBP_FLYER, bank="Goldman Sachs", bank_source="top_text")
    meta = check_metadata(email, llm_output(bank="UBP", date=None, date_quote=None))
    assert (meta.bank, meta.bank_source) == ("UBP", "llm")
    assert (meta.bank_llm, meta.bank_python) == ("UBP", "Goldman Sachs")


def test_model_bank_not_named_in_the_email_falls_back_to_python():
    meta = check_metadata(prepared_email(), llm_output(bank="Barclays"))
    assert (meta.bank, meta.bank_source) == ("Deutsche Bank", "python:logo")


def test_model_unsure_about_bank_is_not_a_conflict():
    meta = check_metadata(prepared_email(), llm_output(bank="Other"))
    assert (meta.bank, meta.bank_source) == ("Deutsche Bank", "python:logo")


def test_model_fills_a_missing_bank_only_when_the_email_names_it():
    email = prepared_email(bank=None, bank_source=None, body="Banque Pictet & Cie SA\nDaily Letter")
    assert check_metadata(email, llm_output(bank="Pictet")).bank == "Pictet"
    assert check_metadata(email, llm_output(bank="Barclays")).bank is None


def test_date_agreement():
    meta = check_metadata(prepared_email(), llm_output())
    assert (meta.date, meta.date_source) == (date(2026, 4, 10), "llm+python")


def test_model_date_wins_when_its_quote_checks_out():
    email = prepared_email(
        body="[image: Deutsche Bank Logo]\nPublished 9 April 2026\nTrade date 10 April 2026"
    )
    meta = check_metadata(email, llm_output(date="2026-04-09", date_quote="9 April 2026"))
    assert (meta.date, meta.date_source) == (date(2026, 4, 9), "llm")
    assert (meta.date_llm, meta.date_python) == (date(2026, 4, 9), date(2026, 4, 10))


def test_the_title_is_taken_as_the_email_writes_it():
    # 035331: the export lost a dash; the AI guessed "\x96" in its place
    email = prepared_email(body=f"SPECIAL EDITION {chr(0xFFFD)} U.S. and Iran Reach Fragile Truce")
    output = llm_output(title=f"SPECIAL EDITION {chr(0x96)} U.S. and Iran Reach Fragile Truce")
    meta = check_metadata(email, output)
    assert meta.title == f"SPECIAL EDITION {chr(0xFFFD)} U.S. and Iran Reach Fragile Truce"
    assert meta.title_verified
    # a title that is not a whole line is kept as the AI wrote it
    assert check_metadata(email, llm_output(title="Fragile Truce")).title == "Fragile Truce"


def test_rules_date_is_never_used_on_its_own():
    email = prepared_email(body="Deutsche Bank\n10 April 2026\nTrade on 9 April")
    meta = check_metadata(email, llm_output(date="2026-04-09", date_quote="9 April"))
    assert (meta.date, meta.date_problem) == (None, "no_full_date")
    meta = check_metadata(prepared_email(), llm_output(date=None, date_quote=None))
    assert (meta.date, meta.date_python) == (None, date(2026, 4, 10))


def test_both_readers_agreeing_confirms_a_date_despite_a_short_quote():
    meta = check_metadata(prepared_email(), llm_output(date="2026-04-10", date_quote="10 April"))
    assert (meta.date, meta.date_source, meta.date_problem) == (
        date(2026, 4, 10),
        "llm+python",
        None,
    )


def test_weekday_quote_without_a_year_is_confirmed():
    # 035427: the email only says "Monday, 13 April"
    email = prepared_email(date=None, date_source=None, body="UBS House View\nMonday, 13 April")
    output = llm_output(date="2026-04-13", date_quote="Monday, 13 April")
    assert check_metadata(email, output).date == date(2026, 4, 13)
    # the weekday decides the year, not the model
    wrong_year = llm_output(date="2025-04-13", date_quote="Monday, 13 April")
    assert check_metadata(email, wrong_year).date == date(2026, 4, 13)


def test_the_date_is_read_from_the_quote_not_from_the_model():
    # 035253: the model read "02.04.2026" as 4 February; the email means 2 April
    email = prepared_email(body="Julius Baer\nResearch | 02.04.2026", received=date(2026, 4, 2))
    meta = check_metadata(email, llm_output(date="2026-02-04", date_quote="02.04.2026"))
    assert (meta.date, meta.date_llm, meta.date_problem) == (
        date(2026, 4, 2),
        date(2026, 2, 4),
        None,
    )


def test_a_quote_with_several_dates_keeps_the_ai_date_when_it_is_one_of_them():
    body = "Report period: 31 March 2026; published 2 April 2026"
    email = prepared_email(date=None, date_source=None, body=body, received=date(2026, 4, 2))
    quote = "Report period: 31 March 2026; published 2 April 2026"
    assert check_metadata(email, llm_output(date="2026-04-02", date_quote=quote)).date == date(
        2026, 4, 2
    )
    # neither date is the AI's, so the quote is unclear and nothing is used
    meta = check_metadata(email, llm_output(date="2026-04-01", date_quote=quote))
    assert (meta.date, meta.date_problem) == (None, "unclear_quote")


def test_link_date_is_used_only_when_no_date_is_confirmed():
    email = prepared_email(date=None, date_source=None, date_hint=date(2026, 4, 13))
    meta = check_metadata(email, llm_output(date=None, date_quote=None))
    assert (meta.date, meta.date_source) == (date(2026, 4, 13), "link")
    meta = check_metadata(prepared_email(date_hint=date(2026, 4, 13)), llm_output())
    assert (meta.date, meta.date_source) == (date(2026, 4, 10), "llm+python")


def test_model_fills_a_missing_date_from_pdf_text():
    email = prepared_email(
        date=None,
        date_source=None,
        llm_input="EMAIL BODY:\nDeutsche Bank\n\nPDF TEXT (note.pdf):\nTechnip 8 April 2026",
    )
    meta = check_metadata(email, llm_output(date="2026-04-08", date_quote="8 April 2026"))
    assert (meta.date, meta.date_source) == (date(2026, 4, 8), "llm")


def test_model_date_after_arrival_is_rejected():
    # 035243: the subscription deadline is the only date it contains
    email = prepared_email(
        date=None,
        date_source=None,
        received=date(2026, 4, 9),
        body="Subscription period until: 17.04.2026, 15:00 Geneva time",
    )
    meta = check_metadata(email, llm_output(date="2026-04-17", date_quote="17.04.2026"))
    assert (meta.date, meta.date_llm, meta.date_problem) == (
        None,
        date(2026, 4, 17),
        "after_arrival",
    )
