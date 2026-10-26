import pytest

from pipeline.repair_text import (
    APOSTROPHE,
    CLOSE_QUOTE,
    EM_DASH,
    EN_DASH,
    EURO,
    OPEN_QUOTE,
    POUND,
    R,
    repair,
)

A = APOSTROPHE


@pytest.mark.parametrize(
    "damaged, repaired",
    [
        (
            f"the company{R}s view: we{R}ll see, don{R}t",
            f"the company{A}s view: we{A}ll see, don{A}t",
        ),
        (f"what we{R}{R}ve learned", f"what we{A}ve learned"),
        (
            f"Union Bancaire Priv{R}e",
            "Union Bancaire Priv" + chr(0xE9) + "e",
        ),
        (
            f"the {R}Bank{R} and the {R}Views{R}",
            f"the {OPEN_QUOTE}Bank{CLOSE_QUOTE} and the {OPEN_QUOTE}Views{CLOSE_QUOTE}",
        ),
        (f"the beneficiaries{R} rights", f"the beneficiaries{A} rights"),
        (f"utilities{R}not staples", f"utilities{EM_DASH}not staples"),
        (f"Mexico {R} Short-term outlook", f"Mexico {EN_DASH} Short-term outlook"),
        (f"Copyright {R} 2026 Deutsche Bank", "Copyright " + chr(0xA9) + " 2026 Deutsche Bank"),
        (f"since Aug {R}20 and in Q4{R}25", f"since Aug {A}20 and in Q4{A}25"),
        (f"200{R}000 USD for 2026{R}2028", f"200{A}000 USD for 2026{EN_DASH}2028"),
        (f"revenue reached {R}848M", f"revenue reached {EURO}848M"),
        (f"redress scheme at about {R}320M", f"redress scheme at about {POUND}320M"),
        (
            f"I lean towards selling upside{R} I just don{R}t",
            f"I lean towards selling upside {EN_DASH} I just don{A}t",
        ),
    ],
)
def test_lost_characters_are_put_back_from_their_context(damaged, repaired):
    assert repair(damaged) == repaired


def test_a_sign_alone_in_its_element_was_a_bullet():
    assert repair(f"\n{R}{R}") == "\n" + chr(0x2022)


def test_text_without_the_sign_is_untouched():
    text = "Rates rallied, it's done"
    assert repair(text) is text
