from pathlib import Path

import pandas as pd
import pytest

from budget.categorizer import categorize, load_rules, parse_rules

ROOT = Path(__file__).parent.parent


def tx(counterparty="", message="", raw_category="", amount=-1.0) -> dict:
    return {"counterparty": counterparty, "message": message, "raw_category": raw_category, "amount": amount}


def run(rules: dict, *rows: dict) -> pd.DataFrame:
    return categorize(pd.DataFrame(list(rows)), parse_rules(rules))


GROUPS = {"a": "variable", "b": "fixed", "inc": "income"}


def test_first_matching_rule_wins():
    rules = {
        "groups": GROUPS,
        "rules": [
            {"category": "a", "match": {"counterparty": "shop"}},
            {"category": "b", "match": {"counterparty": "shop one"}},
        ],
    }
    df = run(rules, tx(counterparty="Shop One"))
    assert df.loc[0, "category"] == "a"
    assert df.loc[0, "group"] == "variable"


def test_match_is_case_insensitive_search():
    rules = {"groups": GROUPS, "rules": [{"category": "a", "match": {"message": "najom"}}]}
    assert run(rules, tx(message="Platba NAJOM 09"))["category"][0] == "a"


def test_all_conditions_must_hold():
    rules = {
        "groups": GROUPS,
        "rules": [{"category": "b", "match": {"counterparty": "landlord", "message": "rent"}}],
    }
    df = run(rules, tx(counterparty="Landlord", message="rent"), tx(counterparty="Landlord", message="deposit"))
    assert df["category"].tolist() == ["b", None]


def test_amount_sign_condition():
    rules = {
        "groups": GROUPS,
        "rules": [{"category": "inc", "match": {"raw_category": "prijata", "amount": "positive"}}],
    }
    df = run(rules, tx(raw_category="Prijata platba", amount=100.0), tx(raw_category="Prijata platba", amount=-5.0))
    assert df["category"].tolist() == ["inc", None]
    assert df["group"].tolist() == ["income", None]


def test_uncategorized_is_none():
    rules = {"groups": GROUPS, "rules": [{"category": "a", "match": {"counterparty": "x"}}]}
    df = run(rules, tx(counterparty="abc"))
    assert df.loc[0, "category"] is None
    assert df.loc[0, "group"] is None


@pytest.mark.parametrize(
    ("rules", "error"),
    [
        ({"groups": {"a": "luxury"}, "rules": []}, "unknown group"),
        ({"groups": GROUPS, "rules": [{"category": "zzz", "match": {"message": "x"}}]}, "not defined in groups"),
        ({"groups": GROUPS, "rules": [{"category": "a", "match": {"message": "("}}]}, "invalid regex"),
        ({"groups": GROUPS, "rules": [{"category": "a", "match": {"iban": "x"}}]}, "unknown match field"),
        ({"groups": GROUPS, "rules": [{"category": "a", "match": {"amount": "big"}}]}, "amount must be"),
        ({"groups": GROUPS, "rules": [{"category": "a", "match": {}}]}, "empty match"),
    ],
)
def test_invalid_rules_raise(rules, error):
    with pytest.raises(ValueError, match=error):
        parse_rules(rules)


def test_shipped_rules_file_is_valid():
    ruleset = load_rules(ROOT / "examples/demo/rules.yaml")
    assert ruleset.rules


def test_sample_rules_categorize_income_and_rent():
    ruleset = load_rules(ROOT / "examples/demo/rules.yaml")
    df = categorize(
        pd.DataFrame(
            [
                tx(counterparty="Example Employer", raw_category="Prijata platba", amount=2000.0),
                tx(counterparty="Landlord Name", raw_category="Trvaly prikaz", amount=-650.0),
            ]
        ),
        ruleset,
    )
    assert df["category"].tolist() == ["salary", "rent"]
    assert df["group"].tolist() == ["income", "fixed"]


def test_rule_index_points_to_winning_rule():
    rules = {
        "groups": GROUPS,
        "rules": [
            {"category": "a", "match": {"counterparty": "nomatch"}},
            {"category": "b", "match": {"counterparty": "shop"}},
            {"category": "a", "match": {"counterparty": "shop one"}},
        ],
    }
    df = run(rules, tx(counterparty="Shop One"), tx(counterparty="other"))
    assert df["rule_index"].tolist() == [1, None]
