from pipeline.tag_rules import apply_tag_rules, clean_companies
from tests.factories import checklist, llm_output


def test_real_model_mistakes_are_corrected():
    # what gpt-oss 20B returned for Goldman's "Macro at a Glance" with a one line prompt
    output = llm_output(
        primary_asset_tag="Macro",
        asset_tags=["Energy", "Commodities", "Macro", "Energy", "Credit Strategy"],
    )
    tags = apply_tag_rules(output)
    assert tags.market_wrap == "NO"
    assert tags.asset_tags == ["Macro", "Commodities", "Energy", "Fixed Income", "Credit Strategy"]
    assert tags.corrections == ["added parent Fixed Income for Credit Strategy"]


def test_model_saying_yes_forces_the_market_wrap_values():
    output = llm_output(
        market_wrap="YES",
        market_wrap_checklist=checklist(yes=5),
        primary_asset_tag="Equity",
        asset_tags=["Equity", "Company Research"],
        companies_mentioned=["Apple"],
        industry_subindustry=["TECHNOLOGY > Hardware"],
    )
    tags = apply_tag_rules(output)
    assert (tags.market_wrap, tags.primary_asset_tag, tags.asset_tags) == (
        "YES",
        "Market Wrap",
        ["Market Wrap"],
    )
    assert (tags.companies_mentioned, tags.industry_subindustry) == ([], [])


def test_the_model_decides_not_a_checklist_count():
    # all seven groups true, yet the model judged it is not a wrap: its decision stands
    output = llm_output(market_wrap="NO", market_wrap_checklist=checklist(yes=7))
    assert apply_tag_rules(output).market_wrap == "NO"
    # and the other way round
    output = llm_output(market_wrap="YES", market_wrap_checklist=checklist(yes=0))
    assert apply_tag_rules(output).market_wrap == "YES"


def test_market_wrap_tag_removed_when_the_model_says_no():
    output = llm_output(primary_asset_tag="Market Wrap", asset_tags=["Market Wrap", "JPY"])
    tags = apply_tag_rules(output)
    assert (tags.primary_asset_tag, tags.asset_tags) == ("FX", ["FX", "JPY"])
    assert "removed Market Wrap tag: the model decided it is not a market wrap" in tags.corrections


def test_market_wrap_with_nothing_else_leaves_no_class():
    tags = apply_tag_rules(llm_output(primary_asset_tag="Market Wrap", asset_tags=[]))
    assert (tags.primary_asset_tag, tags.asset_tags) == (None, [])


def test_companies_and_industries_need_an_equity_tag():
    output = llm_output(
        companies_mentioned=["Toyota"],
        industry_subindustry=["CONSUMER CYCLICALS > Automobiles"],
    )
    tags = apply_tag_rules(output)
    assert (tags.companies_mentioned, tags.industry_subindustry) == ([], [])
    assert tags.corrections == ["dropped companies and industries without an Equity tag"]


def test_equity_sub_tag_alone_still_counts_as_equity():
    output = llm_output(
        primary_asset_tag="Equity",
        asset_tags=["Company Research"],
        companies_mentioned=["Sartorius"],
        industry_subindustry=["HEALTHCARE > Life Sciences"],
    )
    tags = apply_tag_rules(output)
    assert tags.asset_tags == ["Equity", "Company Research"]
    assert tags.companies_mentioned == ["Sartorius"]


def test_equity_without_industry_becomes_unknown():
    output = llm_output(primary_asset_tag="Equity", asset_tags=["Equity"])
    assert apply_tag_rules(output).industry_subindustry == ["Unknown"]


def test_unknown_is_dropped_next_to_a_real_industry():
    output = llm_output(
        primary_asset_tag="Equity",
        asset_tags=["Equity"],
        industry_subindustry=["Unknown", "ENERGY > Oil", "ENERGY > Oil"],
    )
    assert apply_tag_rules(output).industry_subindustry == ["ENERGY > Oil"]


def test_company_names_are_trimmed_and_deduplicated():
    names = [" Siemens  Healthineers ", "siemens healthineers", "", "Coloplast"]
    assert clean_companies(names) == ["Siemens Healthineers", "Coloplast"]
