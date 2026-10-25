from pipeline.allowed_tags import (
    ASSET_TAXONOMY,
    BANK_NAMES,
    INDUSTRY_TAGS,
    INDUSTRY_TAXONOMY,
    PRIMARY_TAGS,
    SUB_TAGS,
    SUB_TO_PARENT,
)
from pipeline.clean_emails import BANKS


def test_counts_match_the_brief():
    assert len(PRIMARY_TAGS) == 7
    assert len(SUB_TAGS) == 17
    assert len(INDUSTRY_TAXONOMY) == 11
    assert sum(len(subs) for subs in INDUSTRY_TAXONOMY.values()) == 76


def test_each_sub_tag_has_exactly_one_parent():
    assert len(SUB_TO_PARENT) == len(SUB_TAGS)
    assert not set(SUB_TAGS) & set(PRIMARY_TAGS)
    assert SUB_TO_PARENT["Credit Strategy"] == "Fixed Income"


def test_tags_without_sub_tags():
    assert ASSET_TAXONOMY["Thematics"] == []
    assert ASSET_TAXONOMY["Market Wrap"] == []


def test_industry_strings_are_unique_and_formatted():
    assert len(INDUSTRY_TAGS) == len(set(INDUSTRY_TAGS)) == 77
    assert "ENERGY > Gas" in INDUSTRY_TAGS
    assert "UTILITIES > Gas" in INDUSTRY_TAGS
    assert INDUSTRY_TAGS[-1] == "Unknown"
    assert all(" > " in tag for tag in INDUSTRY_TAGS[:-1])


def test_bank_names_cover_every_bank_extraction_can_return():
    assert set(BANKS) | {"Other"} == set(BANK_NAMES)
