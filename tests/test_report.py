import shutil
from pathlib import Path

import pandas as pd
import pytest

from budget.__main__ import main
from budget.categorizer import categorize, parse_rules
from budget.parsers.csob import parse_csob
from budget.report import load_transactions, monthly_summary

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"
RULES = {
    "groups": {"sport": "variable", "rent": "fixed", "salary": "income"},
    "rules": [
        {"category": "sport", "match": {"counterparty": "gym"}},
        {"category": "rent", "match": {"message": "najom"}},
        {"category": "salary", "match": {"raw_category": "prijata", "amount": "positive"}},
    ],
}
RULES_YAML = """
groups: {sport: variable, rent: fixed, salary: income}
rules:
  - {category: sport, match: {counterparty: gym}}
  - {category: rent, match: {message: najom}}
  - {category: salary, match: {raw_category: prijata, amount: positive}}
"""


@pytest.fixture
def categorized() -> pd.DataFrame:
    return categorize(parse_csob(FIXTURE), parse_rules(RULES))


def test_monthly_totals(categorized):
    s = monthly_summary(categorized, "2026-09")
    assert s.income == 2500.0
    assert s.fixed == -650.0
    # gym -11 categorized + uncategorized -5, -42.30, -20
    assert s.variable == pytest.approx(-78.30)
    assert s.balance == pytest.approx(1771.70)
    assert s.by_category.to_dict() == {"rent": -650.0, "sport": -11.0, "salary": 2500.0}


def test_uncategorized_listed(categorized):
    s = monthly_summary(categorized, "2026-09")
    assert sorted(s.uncategorized["amount"]) == [-42.30, -20.0, -5.0]


def test_month_filter():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-31", "2026-09-01", "2026-10-01"]),
            "amount": [-1.0, -2.0, -4.0],
            "counterparty": ["x", "x", "x"],
            "message": ["", "", ""],
            "raw_category": ["", "", ""],
            "category": ["a", "a", "a"],
            "group": ["fixed", "fixed", "fixed"],
        }
    )
    s = monthly_summary(df, "2026-09")
    assert s.fixed == -2.0
    assert s.income == 0.0
    assert s.uncategorized.empty


def test_uncategorized_positive_counts_as_income():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01"]),
            "amount": [30.0],
            "counterparty": ["friend"],
            "message": [""],
            "raw_category": [""],
            "category": [None],
            "group": [None],
        }
    )
    assert monthly_summary(df, "2026-09").income == 30.0


def test_overlapping_exports_are_deduplicated(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "a.csv")
    shutil.copy(FIXTURE, tmp_path / "b.csv")
    assert len(load_transactions(tmp_path)) == 6


def test_identical_rows_within_one_file_are_kept(tmp_path):
    lines = FIXTURE.read_text().splitlines()
    (tmp_path / "a.csv").write_text("\n".join(lines[:4] + [lines[3]]) + "\n")
    shutil.copy(tmp_path / "a.csv", tmp_path / "b.csv")
    assert len(load_transactions(tmp_path)) == 2


def test_cli_report(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE, data / "export.csv")
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML)

    private = tmp_path / "no_private.yaml"  # never read the real private.yaml in tests
    args = ["report", "--month", "2026-09", "--data", str(data), "--rules", str(rules), "--private", str(private)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "balance        1771.70" in out
    assert "Uncategorized (3):" in out
    assert "Shop One, Branch 2" in out


def test_cli_report_rejects_bad_month(capsys):
    assert main(["report", "--month", "2026-9"]) == 2
    assert "YYYY-MM" in capsys.readouterr().err


def test_cli_report_missing_data_dir(tmp_path, capsys):
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES_YAML)
    args = ["report", "--month", "2026-09", "--data", str(tmp_path / "none"), "--rules", str(rules)]
    assert main([*args, "--private", str(tmp_path / "no_private.yaml")]) == 1  # never read the real private.yaml
    assert "no *.csv" in capsys.readouterr().err


def test_counterparties_have_no_amounts(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE, data / "export.csv")
    private = tmp_path / "private.yaml"
    private.write_text("patterns:\n  - 'test gym'\n")

    args = ["counterparties", "--month", "2026-09", "--data", str(data), "--private", str(private)]
    assert main(args + ["--exclude-type", "Odoslana platba"]) == 0
    out = capsys.readouterr().out
    assert "Shop One, Branch 2 | Platba kartou" in out
    assert "<private> | Platba kartou" in out
    assert "TEST GYM" not in out
    assert "Friend Name" not in out
    assert "2500" not in out and "650" not in out


def test_transfer_group_is_excluded_from_balance():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "amount": [-100.0, 50.0],
            "counterparty": ["broker", "shop"],
            "message": ["", ""],
            "raw_category": ["", ""],
            "category": ["investments", "refund"],
            "group": ["transfer", "variable"],
        }
    )
    s = monthly_summary(df, "2026-09")
    assert s.transfer == -100.0
    assert s.balance == 50.0


def test_monthly_trend_and_partial(categorized):
    from budget.report import monthly_trend

    extra = categorized.iloc[[0]].assign(date=pd.Timestamp("2026-10-02"))
    df = pd.concat([categorized, extra], ignore_index=True)
    trend = monthly_trend(df)
    assert trend["month"].tolist() == ["2026-09", "2026-10"]
    assert trend["partial"].tolist() == [False, True]
    assert trend.loc[0, "balance"] == pytest.approx(1771.70)
    assert monthly_summary(df, "2026-10").partial is True
