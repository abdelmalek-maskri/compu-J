"""the brief's tag lists: the one source for the schema, the prompt and the dashboard filters"""

from pipeline.prepare import BANKS

ASSET_TAXONOMY: dict[str, list[str]] = {
    "Macro": ["Developed Markets", "Emerging Markets"],
    "Fixed Income": ["Credit Strategy", "Rates Strategy", "Securitisation"],
    "Equity": ["Company Research", "Portfolio Strategy", "Thematic Investing"],
    "Commodities": ["Energy", "Metals", "Agriculture"],
    "FX": ["USD", "EUR", "JPY", "GBP", "CHF", "Other"],
    "Thematics": [],
    "Market Wrap": [],
}

INDUSTRY_TAXONOMY: dict[str, list[str]] = {
    "BASIC MATERIALS": ["Agriculture", "Chemicals", "Metals & Mining", "Paper & Forest", "Steel"],
    "CONSUMER STAPLES": ["Beverages", "Consumer Products", "Food", "Retail", "Tobacco"],
    "CONSUMER CYCLICALS": [
        "Automobiles", "Branded Consumer Goods", "Business Services", "Consumer Durables",
        "Education", "Entertainment & Leisure", "Gaming", "Housing", "Lodging", "Media",
        "Restaurants & Pubs", "Retail", "Textile, Apparel & Footwear", "Travel",
    ],
    "ENERGY": ["Clean Energy", "Energy", "Gas", "Oil", "Oil Services"],
    "FINANCIAL SERVICES": [
        "Banks", "Brokers & Asset Managers", "Capital Markets", "Diversified Financials",
        "Insurance", "Real Estate", "Specialty Finance",
    ],
    "HEALTHCARE": [
        "Biotechnology", "Healthcare Services", "Life Sciences", "Medical Technology",
        "Pharmaceuticals",
    ],
    "INDUSTRIALS": [
        "Aerospace & Defense", "Capital Goods", "Construction", "Electrical Equipment",
        "Environmental Services", "Machinery", "Multi-Industry", "Packaging",
    ],
    "TECHNOLOGY": [
        "Communications Technology", "Hardware", "Info Services", "Internet", "IT Services",
        "Semiconductors", "Software", "Technology",
    ],
    "TELECOM SERVICES": [
        "Communication Services", "Satellite", "Telecom Services", "Telecom Wireless", "Towers",
    ],
    "TRANSPORTATION": [
        "Air Freight", "Airlines", "Airports", "Infrastructure", "Logistics", "Railroads",
        "Shipping", "Trucking",
    ],
    "UTILITIES": ["Diversified", "Gas", "MLPs", "Power", "Utilities", "Water"],
}  # fmt: skip

PRIMARY_TAGS = tuple(ASSET_TAXONOMY)
SUB_TAGS = tuple(sub for subs in ASSET_TAXONOMY.values() for sub in subs)
ASSET_TAGS = PRIMARY_TAGS + SUB_TAGS
SUB_TO_PARENT = {sub: parent for parent, subs in ASSET_TAXONOMY.items() for sub in subs}
MARKET_WRAP = "Market Wrap"
EQUITY = "Equity"

# "Gas" and "Retail" each sit under two sectors, so only the full string is unique
UNKNOWN_INDUSTRY = "Unknown"
INDUSTRY_TAGS = (
    *(f"{sector} > {sub}" for sector, subs in INDUSTRY_TAXONOMY.items() for sub in subs),
    UNKNOWN_INDUSTRY,
)

BANK_NAMES = (*BANKS, "Other")
