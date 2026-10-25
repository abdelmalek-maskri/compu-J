from datetime import date

from pipeline.check_metadata import appears_in, merge_metadata
from tests.factories import llm_output, prepared_email


def test_title_found_despite_spacing_case_and_curly_quotes():
    text = "UBS House View \u201cAffording\u00a0a war\u201d \u2013 April"
    assert appears_in('ubs house view "affording a war" - april', text)
    assert not appears_in("UBS House View: Driving fuel demand", text)
    assert not appears_in("", text)


def test_title_not_in_the_email_is_marked_unverified():
    meta = merge_metadata(prepared_email(), llm_output(title="Weekly FX Outlook"))
    assert (meta.title, meta.title_verified) == ("Weekly FX Outlook", False)
    assert merge_metadata(prepared_email(), llm_output()).title_verified


def test_bank_agreement_is_confirmed():
    meta = merge_metadata(prepared_email(), llm_output(bank="Deutsche Bank"))
    assert (meta.bank, meta.bank_source, meta.conflicts) == ("Deutsche Bank", "logo+llm", [])


def test_bank_disagreement_keeps_python_and_records_it():
    meta = merge_metadata(prepared_email(), llm_output(bank="Barclays"))
    assert (meta.bank, meta.bank_source) == ("Deutsche Bank", "logo")
    assert meta.conflicts == ["bank: rules found Deutsche Bank, model said Barclays"]


def test_model_unsure_about_bank_is_not_a_conflict():
    meta = merge_metadata(prepared_email(), llm_output(bank="Other"))
    assert (meta.bank, meta.conflicts) == ("Deutsche Bank", [])


def test_model_fills_a_missing_bank():
    meta = merge_metadata(prepared_email(bank=None, bank_source=None), llm_output(bank="Pictet"))
    assert (meta.bank, meta.bank_source) == ("Pictet", "llm")


def test_date_agreement_is_confirmed():
    meta = merge_metadata(prepared_email(), llm_output())
    assert (meta.date, meta.date_source) == (date(2026, 4, 10), "text+llm")


def test_date_disagreement_keeps_python_and_records_it():
    meta = merge_metadata(prepared_email(), llm_output(date="2026-04-09", date_quote="9 April"))
    assert meta.date == date(2026, 4, 10)
    assert meta.conflicts == ["date: rules found 2026-04-10, model said 2026-04-09"]


def test_model_fills_a_missing_date_from_pdf_text_when_the_quote_checks_out():
    email = prepared_email(
        date=None,
        date_source=None,
        llm_input="EMAIL BODY:\nDear all,\n\nPDF TEXT (note.pdf):\nTechnip Energies 8 April 2026",
    )
    meta = merge_metadata(email, llm_output(date="2026-04-08", date_quote="8 April 2026"))
    assert (meta.date, meta.date_source, meta.conflicts) == (date(2026, 4, 8), "llm", [])


def test_model_date_rejected_when_quote_is_not_in_the_email():
    email = prepared_email(date=None, date_source=None, body="Dear Client, please find attached.")
    meta = merge_metadata(email, llm_output(date="2026-04-10", date_quote="10 April 2026"))
    assert (meta.date, meta.date_source) == (None, None)
    assert "does not check out" in meta.conflicts[0]


def test_model_date_rejected_when_quote_says_another_date():
    email = prepared_email(date=None, date_source=None, body="Published 9 April 2026")
    meta = merge_metadata(email, llm_output(date="2026-04-10", date_quote="9 April 2026"))
    assert meta.date is None


def test_model_date_after_arrival_is_rejected_like_pythons():
    # 035243: the flyer's subscription deadline is the only date it contains
    email = prepared_email(
        date=None,
        date_source=None,
        received=date(2026, 4, 9),
        body="Subscription period until: 17.04.2026, 15:00 Geneva time",
    )
    meta = merge_metadata(email, llm_output(date="2026-04-17", date_quote="17.04.2026"))
    assert meta.date is None
