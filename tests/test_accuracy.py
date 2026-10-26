from scripts.accuracy import pick_sample, report, score


def record(email: str, primary: str, **over) -> dict:
    return {
        "source_file": email,
        "bank": "UBS",
        "date": "2026-04-10",
        "market_wrap": "NO",
        "primary_asset_tag": primary,
        **over,
    }


def test_the_sample_takes_every_main_class_in_turn():
    records = [record(f"0353{i:02}", "Equity") for i in range(10)]
    records += [record("035390", "FX"), record("035391", "Macro")]

    picked = pick_sample(records, 4)

    assert {"035390", "035391"} <= set(picked) and len(picked) == 4
    assert pick_sample(records, 4) == picked


def test_scores_the_submitted_answer_and_both_readers_separately():
    records = {
        "035300": record("035300", "FX", date=None),
        "035301": record("035301", "Macro"),
    }
    details = {
        "035300": {"bank_llm": "UBS", "bank_python": "UBS", "date_llm": None, "date_python": None},
        "035301": {
            "bank_llm": "UBS",
            "bank_python": "Barclays",
            "date_llm": "2026-04-10",
            "date_python": None,
        },
    }
    columns = ["email", "bank", "date", "market_wrap", "primary_asset_tag"]
    labels = [
        dict(zip(columns, ["035300", "ubs", "none", "NO", ""], strict=True)),
        dict(zip(columns, ["035301", "UBS", "2026-04-10", "YES", "Macro"], strict=True)),
    ]

    result = score(labels, records, details)

    assert result["bank"]["submitted"][:2] == (2, 2)
    assert result["bank"]["rules alone"][:2] == (1, 2)
    assert result["date"]["rules alone"][:2] == (1, 2)  # 035300 rightly has no date
    assert result["market_wrap"]["submitted"][:2] == (1, 2)
    assert result["primary_asset_tag"]["submitted"][:2] == (1, 1)  # an empty cell is skipped
    assert "model alone" not in result["market_wrap"]
    assert "* 035301 market_wrap: labelled 'YES', submitted 'NO'" in report(result)
