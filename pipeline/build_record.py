"""assemble the final classified_emails.json entry for one email"""

from pipeline.check_metadata import check_metadata
from pipeline.clean_emails import PreparedEmail
from pipeline.flags import link_date_flags, logic_flags, metadata_flags
from pipeline.repair_text import repair
from pipeline.reviewed import SETTLES, Reviewed
from pipeline.schema import ClassifiedEmail, LLMOutput, Meta
from pipeline.tag_rules import apply_tag_rules


def build_record(
    email: PreparedEmail,
    output: LLMOutput,
    model: str,
    prompt_version: str,
    reviewed: list[Reviewed] = (),
) -> ClassifiedEmail:
    tags = apply_tag_rules(output.model_copy(update={r.field: r.value for r in reviewed}))
    meta = check_metadata(email, output)
    settled = {field for r in reviewed for field in SETTLES[r.field]}
    flags = [f for f in metadata_flags(meta) + logic_flags(output) if f.field not in settled]
    # the title is checked against the text as exported, then repaired for people to read
    return ClassifiedEmail(
        folder_name=meta.title and repair(meta.title),
        bank=meta.bank,
        date=meta.date,
        market_wrap=tags.market_wrap,
        primary_asset_tag=tags.primary_asset_tag,
        asset_tags=tags.asset_tags,
        companies_mentioned=[repair(c) for c in tags.companies_mentioned],
        industry_subindustry=tags.industry_subindustry,
        pdf_attachment=email.attachments.pdfs or None,
        source_file=email.id,
        meta=Meta(
            bank_source=meta.bank_source,
            date_source=meta.date_source,
            date_quote=meta.date_quote,
            received=email.received,
            title_verified=meta.title_verified,
            bank_llm=meta.bank_llm,
            bank_python=meta.bank_python,
            date_llm=meta.date_llm,
            date_python=meta.date_python,
            flags=flags + link_date_flags(meta.date, meta.date_source),
            corrections=tags.corrections,
            reviewed=[r.note() for r in reviewed],
            content_type=output.content_type,
            market_wrap_checklist=output.market_wrap_checklist,
            duplicate_of=email.duplicate_of,
            warnings=email.warnings,
            model=model,
            prompt_version=prompt_version,
        ),
    )


def error_record(
    email: PreparedEmail, error: str, model: str, prompt_version: str
) -> ClassifiedEmail:
    """the LLM call failed: keep everything Python found so the email still appears. the
    rules' date is still never used on its own; it stays in date_python for review"""
    found = email.date_hint
    source = "link" if found else None
    return ClassifiedEmail(
        folder_name=None,
        bank=email.bank,
        date=found,
        market_wrap=None,
        primary_asset_tag=None,
        asset_tags=[],
        companies_mentioned=[],
        industry_subindustry=[],
        pdf_attachment=email.attachments.pdfs or None,
        source_file=email.id,
        meta=Meta(
            bank_source=f"python:{email.bank_source}" if email.bank else None,
            date_source=source,
            bank_python=email.bank,
            date_python=email.date,
            received=email.received,
            flags=link_date_flags(found, source),
            duplicate_of=email.duplicate_of,
            warnings=email.warnings,
            error=error,
            model=model,
            prompt_version=prompt_version,
        ),
    )
