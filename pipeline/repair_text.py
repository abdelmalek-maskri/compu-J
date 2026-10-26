"""put back the characters the export lost

the exporter replaced every character it could not read with the replacement sign U+FFFD, so
"company's", "Privee" with its accent, "(c) 2026" and "EUR 2bn" arrived as "company?s",
"Priv?e", "? 2026" and "?2bn" (119 of the 200 emails). the original character is gone; each
one is put back from what is around it: the words it sits in, the rules of English
punctuation, and for currencies the companies the sentence is about

this is for people reading the emails (the dashboard, the titles). the model reads the text as
exported, so its saved answers stay valid
"""

import re

R = "\ufffd"
APOSTROPHE = "\u2019"
OPEN_QUOTE = "\u201c"
CLOSE_QUOTE = "\u201d"
EN_DASH = "\u2013"
EM_DASH = "\u2014"
EURO = "\u20ac"
POUND = "\u00a3"
YEN = "\u00a5"

# whole words, checked first: accented names and words, mostly from the banks' legal footers
WORDS = {
    f"Priv{R}e": "Priv\u00e9e",
    f"Contr{R}le": "Contr\u00f4le",
    f"Rh{R}ne": "Rh\u00f4ne",
    f"R{R}solution": "R\u00e9solution",
    f"Financi{R}res": "Financi\u00e8res",
    f"Activit{R}s": "Activit\u00e9s",
    f"Principaut{R}": "Principaut\u00e9",
    f"Autorit{R}": "Autorit\u00e9",
    f"D{R}p{R}ts": "D\u00e9p\u00f4ts",
    f"Syst{R}me": "Syst\u00e8me",
    f"R{R}pertoire": "R\u00e9pertoire",
    f"Ch{R}ne": "Ch\u00eane",
    f"Ars{R}ne": "Ars\u00e8ne",
    f"Herm{R}s": "Herm\u00e8s",
    f"Kirchnerstra{R}e": "Kirchnerstra\u00dfe",
    f"Z{R}rich": "Z\u00fcrich",
    f"T{R}rkiye": "T\u00fcrkiye",
    f"Ler{R}y": "Ler\u00f8y",
    f"Telefon{R}a": "Telefon\u00eda",
    f"Escrit{R}rio": "Escrit\u00f3rio",
    f"L{R}pez": "L\u00f3pez",
    f"Vicu{R}a": "Vicu\u00f1a",
    f"{R}lvarez": "\u00c1lvarez",
    f"BOTA{R}": "BOTA\u015e",  # the Turkish gas company
    f"vis-{R}-vis": "vis-\u00e0-vis",
    f"S{R}mores": f"S{APOSTROPHE}mores",
    f"{R}STR": f"{EURO}STR",  # the euro short-term rate
    f"6{R} Dto": "6\u00ba Dto",  # a Portuguese address: "n.o 131 - 6o Dto."
}

# sentences where the currency is not the euro, or the sign is not a currency; the text around
# names the company (Whitbread, Unite and Rightmove report in pounds, PAL Group in yen)
PHRASES = [
    (rf"redress scheme at about {R}", f"redress scheme at about {POUND}"),
    (rf"c{R}(?=800m)", f"c{POUND}"),
    (rf"business rates jumped {R}", f"business rates jumped {POUND}"),
    (rf"BBG consensus {R}", f"BBG consensus {POUND}"),
    (rf"disposal target to > {R}", f"disposal target to > {POUND}"),
    (rf"current {R}(?=100m programme)", f"current {POUND}"),
    (rf"~{R}(?=1\.5bn class action)", f"~{POUND}"),
    (rf"= >{R}(?=5/sh)", f"= >{POUND}"),
    (rf"{R}(?=23[45]\.\d0B)", YEN),
    (rf"noted that {R}(?=98%)", "noted that ~"),
    (rf"{R}(?=\d+(?:\.\d+)?%M)", "\u2212"),  # "-0.3%M": a minus sign
    (rf"only {R}%", "only \u00bd%"),
    (rf"\$ vs\. {R},", f"$ vs. {EURO},"),
    (rf"\bn\.{R}(?= \d)", "n.\u00ba"),
    (rf"remain: {R}1\)", "remain: 1)"),
    # "(see ?" a linked title "?)", the link being its own element
    (rf"\(see\s{R}\s?", f"(see {OPEN_QUOTE}"),
    (rf"\s?{R}(?=\))", CLOSE_QUOTE),
    (rf"{R}(?=\s*Copyright)", "\u00a9"),
]

MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"

# applied in this order; each step only sees the signs the earlier ones left
RULES = [
    # "we??ve": some signs were doubled
    (rf"(?<=\w){R}{R}(?=(?:s|t|ll|re|ve|d|m)\b)", APOSTROPHE),
    (rf"{R}{R}", R),
    # years: "Aug ?20", "Q4?25", "~22x ?27 FCF", "through ?28"
    (rf"\b({MONTH} ){R}(?=\d\d\b)", rf"\1{APOSTROPHE}"),
    (rf"(?<=Q\d){R}(?=\d\d\b)", APOSTROPHE),
    (rf"(?<=x ){R}(?=\d\d [A-Z])", APOSTROPHE),
    (rf"(?<=through ){R}(?=\d\d\b)", APOSTROPHE),
    # "Copyright ? 2026", "? 2026 Morgan Stanley"
    (rf"(?<!\d){R}(?=\s*(?:19|20)\d\d\b(?![\d.,]))", "\u00a9"),
    # "200?000" (Swiss thousands), then ranges "2026?2028", "2?3 weeks"
    (rf"(?<=\d){R}(?=\d{{3}}(?!\d))", APOSTROPHE),
    (rf"(?<=\d){R}(?=\d)", EN_DASH),
    # spaces on both sides make it a dash: "13th ? 17th April", "in 2026 ? and higher"
    (rf"(?<=\S) {R} (?=\d)", f" {EN_DASH} "),
    # every other sign before a number is a currency, and in this research that is the euro
    (rf"{R}(?=\s?\d)", EURO),
    (rf"{R}(?=-Credit)", EURO),
    # contractions and possessives: "it?s", "don?t", "we?ll", "S&P 500?s", "WTB ?s"
    (rf"(?<=[A-Za-z0-9.]){R}(?=(?:s|t|ll|re|ve|d|m)\b)", APOSTROPHE),
    (rf"(?<=\w)\s{R}(?=s\b)", APOSTROPHE),
    (rf"\A{R}(?=s\b)", APOSTROPHE),  # "Kering" in bold, then "?s share price"
    # French elision: "d?Indemnisation", "l?Industrie"
    (rf"(?<=\b[dlDL]){R}(?=[AEIOUHaeiouh])", APOSTROPHE),
    # a dash written without spaces: "utilities?not", "U.S.?Iran", "valuations?X"
    (rf"(?<=[\w).%+]){R}X?(?=[\w(\"])", EM_DASH),
    # alone on its line, or after a run of spaces, it was a bullet; between words, a dash
    (rf"(?:^|(?<=\n)|(?<=\s\s)){R}(?=\s)", "\u2022"),
    (rf"(?<=\s){R}(?=\s)", EN_DASH),
]

WORDS_RE = re.compile("|".join(re.escape(w) for w in WORDS))
PHRASES_RE = [(re.compile(p), r) for p, r in PHRASES]
RULES_RE = [(re.compile(p, re.MULTILINE), r) for p, r in RULES]


def _quotes(text: str) -> str:
    """what is left are quote marks and apostrophes at the edge of a word"""
    out = []
    is_open = False
    for i, ch in enumerate(text):
        if ch != R:
            out.append(ch)
            continue
        before = text[i - 1] if i else " "
        after = text[i + 1] if i + 1 < len(text) else " "
        if (before.isspace() or before in "([{") and not after.isspace():
            out.append(OPEN_QUOTE)
            is_open = True
        elif is_open or before in ".!?,;:":
            out.append(CLOSE_QUOTE)
            is_open = False
        elif before in "sS":
            out.append(APOSTROPHE)  # "beneficiaries? rights", "AWS? largest"
        elif before.isalpha():
            word = re.search(r"\w+$", "".join(out))
            next_word = text[i + 2 : i + 3]
            if after == " " and next_word.isalpha() and word and word.group().islower():
                out.append(" " + EN_DASH)  # chat style notes: "selling upside? I just don't"
            else:
                out.append(CLOSE_QUOTE)  # its opening mark was in another element
        elif not before.isspace():
            out.append(EM_DASH)  # "(2 week ceasefire)? VIX"
        # a sign alone between spaces with nothing to go on is dropped
    return "".join(out)


def repair(text: str) -> str:
    if R not in text:
        return text
    if not text.replace(R, "").strip():
        return text.replace(R + R, R).replace(R, "\u2022")  # a bullet in its own element
    text = WORDS_RE.sub(lambda m: WORDS[m.group(0)], text)
    for pattern, replacement in PHRASES_RE:
        text = pattern.sub(replacement, text)
    for pattern, replacement in RULES_RE:
        text = pattern.sub(replacement, text)
    return _quotes(text)
