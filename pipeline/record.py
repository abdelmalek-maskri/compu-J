"""assemble the final classified_emails.json entry for one email"""

from pipeline.metadata import merge_metadata
from pipeline.prepare import PreparedEmail
from pipeline.rules import apply_tag_rules
from pipeline.schema import ClassifiedEmail, LLMOutput, Meta


def build_record(
    email: PreparedEmail, output: LLMOutput, model: str, prompt_version: str
) -> ClassifiedEmail:
    tags = apply_tag_rules(output)
    meta = merge_metadata(email, output)
    return ClassifiedEmail(
        folder_name=meta.title,
        bank=meta.bank,
        date=meta.date,
        market_wrap=tags.market_wrap,
        primary_asset_tag=tags.primary_asset_tag,
        asset_tags=tags.asset_tags,
        companies_mentioned=tags.companies_mentioned,
        industry_subindustry=tags.industry_subindustry,
        pdf_attachment=email.attachments.pdfs or None,
        source_file=email.id,
        meta=Meta(
            bank_source=meta.bank_source,
            date_source=meta.date_source,
            date_quote=meta.date_quote,
            received=email.received,
            title_verified=meta.title_verified,
            conflicts=meta.conflicts,
            corrections=tags.corrections,
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
    """the LLM call failed: keep everything Python found so the email still appears"""
    return ClassifiedEmail(
        folder_name=None,
        bank=email.bank,
        date=email.date,
        market_wrap=None,
        primary_asset_tag=None,
        asset_tags=[],
        companies_mentioned=[],
        industry_subindustry=[],
        pdf_attachment=email.attachments.pdfs or None,
        source_file=email.id,
        meta=Meta(
            bank_source=email.bank_source,
            date_source=email.date_source,
            received=email.received,
            duplicate_of=email.duplicate_of,
            warnings=email.warnings,
            error=error,
            model=model,
            prompt_version=prompt_version,
        ),
    )
