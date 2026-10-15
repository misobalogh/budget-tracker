from pathlib import Path

import pandas as pd
import pytest

from budget.budgets import Budgets, budget_status, load_budgets, parse_budgets, save_budgets


def frame() -> pd.DataFrame:
    rows = [
        # date, amount, category, group
        ("2026-09-02", -300.0, "groceries", "variable"),
        ("2026-09-10", -90.0, "groceries", "variable"),
        ("2026-09-12", 20.0, "groceries", "variable"),  # refund
        ("2026-09-05", -140.0, "restaurants", "variable"),
        ("2026-09-01", -650.0, "rent", "fixed"),
        ("2026-09-15", 2500.0, "salary", "income"),
        ("2026-09-20", -100.0, "investments", "transfer"),
        ("2026-09-21", -30.0, None, None),  # uncategorized expense counts as variable
        ("2026-10-01", -999.0, "groceries", "variable"),  # other month
    ]
    df = pd.DataFrame(rows, columns=["date", "amount", "category", "group"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def by_key(items: list[dict]) -> dict:
    return {(i["kind"], i["key"]): i for i in items}


def test_parse_rounds_and_validates():
    b = parse_budgets({"total": 2000, "groups": {"variable": 1500.555}, "categories": {"groceries": 400}})
    assert b.total == 2000.0 and b.groups == {"variable": 1500.56} and b.categories == {"groceries": 400.0}
    assert parse_budgets(None).is_empty() and parse_budgets({}).is_empty()


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"total": 0}, "greater than zero"),
        ({"total": -5}, "greater than zero"),
        ({"total": "lots"}, "must be a number"),
        ({"total": True}, "must be a number"),
        ({"total": float("nan")}, "greater than zero"),
        ({"groups": {"income": 100}}, "can only be set for"),
        ({"categories": {"": 100}}, "non-empty"),
        ({"weekly": 5}, "unknown key"),
    ],
)
def test_parse_rejects_invalid(data, error):
    with pytest.raises(ValueError, match=error):
        parse_budgets(data)


def test_missing_file_means_no_budgets(tmp_path):
    assert load_budgets(tmp_path / "none.yaml").is_empty()


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "budgets.yaml"
    budgets = Budgets(total=2000.0, groups={"variable": 1500.0}, categories={"restaurants": 100.0, "groceries": 400.0})
    save_budgets(path, budgets)
    assert load_budgets(path) == budgets
    assert path.read_text().index("groceries") < path.read_text().index("restaurants")
    save_budgets(path, Budgets())
    assert load_budgets(path).is_empty()


def test_save_keeps_permissions_of_existing_file(tmp_path):
    path = tmp_path / "budgets.yaml"
    path.write_text("{}\n")
    path.chmod(0o644)
    save_budgets(path, Budgets(total=100.0))
    assert path.stat().st_mode & 0o777 == 0o644


def test_save_rejects_invalid_without_touching_file(tmp_path):
    path = tmp_path / "budgets.yaml"
    save_budgets(path, Budgets(total=100.0))
    before = path.read_text()
    with pytest.raises(ValueError):
        save_budgets(path, Budgets(categories={"groceries": -1.0}))
    assert path.read_text() == before


def test_status_computes_net_spending_per_budget():
    budgets = Budgets(
        total=1500.0,
        groups={"fixed": 700.0, "variable": 400.0},
        categories={"groceries": 400.0, "restaurants": 100.0, "ghost": 50.0},
    )
    items = by_key(budget_status(frame(), budgets, "2026-09", {"groceries": "variable", "restaurants": "variable"}))

    # total = fixed + variable expenses: 300 + 90 - 20 + 140 + 650 + 30 (transfer and income excluded)
    assert items[("total", None)]["spent"] == 1190.0
    assert items[("group", "fixed")]["spent"] == 650.0
    assert items[("group", "variable")]["spent"] == 540.0
    assert items[("category", "groceries")]["spent"] == 370.0  # refund reduces it
    assert items[("category", "groceries")]["remaining"] == 30.0
    assert items[("category", "groceries")]["status"] == "warning"
    assert items[("category", "restaurants")]["status"] == "over"
    assert items[("category", "restaurants")]["remaining"] == -40.0
    assert items[("category", "restaurants")]["ratio"] == 1.4
    assert items[("group", "fixed")]["status"] == "ok"  # 93 % of a fixed limit does not warn
    assert items[("total", None)]["status"] == "ok"
    assert items[("category", "ghost")]["spent"] == 0.0
    assert items[("category", "ghost")]["known"] is False
    assert items[("category", "groceries")]["known"] is True


def test_status_order_is_by_limit_and_empty_month():
    budgets = Budgets(total=100.0, groups={"variable": 100.0}, categories={"a": 100.0, "groceries": 400.0, "restaurants": 100.0})
    items = budget_status(frame(), budgets, "2026-09", {})
    assert [(i["kind"], i["key"]) for i in items] == [
        ("total", None),
        ("group", "variable"),
        ("category", "groceries"),  # limit 400
        ("category", "a"),  # limit 100, ties by name
        ("category", "restaurants"),
    ]
    empty = budget_status(frame(), budgets, "2025-01", {})
    assert all(i["spent"] == 0.0 and i["status"] == "ok" for i in empty)


def test_spent_is_never_negative():
    df = frame()
    df.loc[df["category"] == "restaurants", "amount"] = 50.0  # only refunds
    items = by_key(budget_status(df, Budgets(categories={"restaurants": 100.0}), "2026-09", {"restaurants": "variable"}))
    assert items[("category", "restaurants")]["spent"] == 0.0


def test_fixed_budgets_do_not_warn_until_exceeded():
    budgets = Budgets(groups={"fixed": 650.0}, categories={"rent": 650.0, "groceries": 380.0})
    groups = {"rent": "fixed", "groceries": "variable"}
    items = by_key(budget_status(frame(), budgets, "2026-09", groups))
    assert items[("category", "rent")]["ratio"] == 1.0
    assert items[("category", "rent")]["status"] == "ok"  # paid exactly on schedule
    assert items[("group", "fixed")]["status"] == "ok"
    assert items[("category", "groceries")]["status"] == "warning"  # 370 of 380, a variable budget

    tight = budget_status(frame(), Budgets(categories={"rent": 600.0}, groups={"fixed": 600.0}), "2026-09", groups)
    assert [i["status"] for i in tight] == ["over", "over"]


def test_plan_goals_are_validated_sorted_and_saved(tmp_path):
    from budget.budgets import parse_plan

    plan = parse_plan({"goals": {"2026-11": 5000, "2026-10": 4500.5}})
    assert list(plan.goals) == ["2026-10", "2026-11"] and plan.goals["2026-10"] == 4500.5
    assert not plan.is_empty() and parse_plan({"goals": {}}).is_empty()
    for bad, message in (({"2026-13": 1}, "goal month"), ({"November": 1}, "goal month"), ({"2026-10": 0}, "greater than 0")):
        with pytest.raises(ValueError, match=message):
            parse_plan({"goals": bad})

    path = tmp_path / "budgets.yaml"
    save_budgets(path, Budgets(plan=plan))
    assert load_budgets(path).plan.goals == plan.goals
    assert "goals:" in path.read_text()


def test_plan_start_month_is_validated_and_saved(tmp_path):
    from budget.budgets import parse_plan

    assert parse_plan({"start_month": "2026-10"}).start_month == "2026-10"
    assert not parse_plan({"start_month": "2026-10"}).is_empty()
    for bad in ("October", "2026-13", "2026-1", 202610):
        with pytest.raises(ValueError, match="start month"):
            parse_plan({"start_month": bad})
    path = tmp_path / "budgets.yaml"
    save_budgets(path, Budgets(plan=parse_plan({"start_month": "2026-10", "savings": 500})))
    assert load_budgets(path).plan.start_month == "2026-10"
