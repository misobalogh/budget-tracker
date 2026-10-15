import pandas as pd
import pytest

from budget.budgets import Budgets, Plan, load_budgets, parse_plan, save_budgets
from budget.plan import balance_series, month_plan, savings_by_month


def frame() -> pd.DataFrame:
    rows = [
        ("2026-08-15", 1800.0, "salary", "income"),
        ("2026-08-20", -1400.0, "groceries", "variable"),
        ("2026-09-01", -200.0, "energy", "fixed"),
        ("2026-09-03", -400.0, "groceries", "variable"),
        ("2026-09-15", 1800.0, "salary", "income"),
        ("2026-09-20", -300.0, "savings", "transfer"),  # moved to savings, still "saved"
        ("2026-09-25", -900.0, None, None),  # uncategorized expense counts as variable
    ]
    df = pd.DataFrame(rows, columns=["date", "amount", "category", "group"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_parse_plan_validates():
    plan = parse_plan({"income": 1800, "savings": 300, "min_balance": 4000, "balance": 5200.5, "balance_date": "2026-10-02"})
    assert plan == Plan(1800.0, 300.0, 4000.0, 5200.5, "2026-10-02")
    assert parse_plan(None).is_empty()
    assert parse_plan({"min_balance": 0}).min_balance == 0.0
    assert parse_plan({"balance": -50, "balance_date": "2026-10-02"}).balance == -50.0


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"income": 0}, "greater than 0"),
        ({"savings": -1}, "greater than 0"),
        ({"min_balance": -5}, "greater than -1"),
        ({"income": "lots"}, "must be a number"),
        ({"balance": 100}, "given together"),
        ({"balance_date": "2026-10-02"}, "given together"),
        ({"balance": 100, "balance_date": "yesterday"}, "must be a date"),
        ({"goal": 1}, "unknown key"),
    ],
)
def test_parse_plan_rejects_invalid(data, error):
    with pytest.raises(ValueError, match=error):
        parse_plan(data)


def test_plan_roundtrips_through_the_file_including_unquoted_yaml_dates(tmp_path):
    path = tmp_path / "budgets.yaml"
    plan = Plan(1800.0, 300.0, 4000.0, 5200.0, "2026-10-02")
    save_budgets(path, Budgets(total=1500.0, plan=plan))
    loaded = load_budgets(path)
    assert loaded.plan == plan and loaded.total == 1500.0

    path.write_text("plan:\n  balance: 100\n  balance_date: 2026-10-02\n")  # YAML parses this as a date
    assert load_budgets(path).plan == Plan(balance=100.0, balance_date="2026-10-02")


def test_savings_counts_transfers_as_saved():
    months = {m["month"]: m for m in savings_by_month(frame(), Plan(savings=300.0))}
    assert months["2026-08"]["saved"] == 400.0
    assert months["2026-08"]["met"] is True
    # 1800 income - 200 - 400 - 900 expenses = 300; the 300 transfer is not an expense
    assert months["2026-09"]["saved"] == 300.0
    assert months["2026-09"]["expenses"] == 1500.0
    assert months["2026-09"]["difference"] == 0.0
    assert months["2026-09"]["met"] is True


def test_savings_without_target_and_without_data():
    assert savings_by_month(frame(), Plan())[0]["met"] is None
    assert savings_by_month(pd.DataFrame(), Plan(savings=100.0)) == []


def test_month_plan_allocates_what_is_left_after_savings():
    budgets = Budgets(total=1700.0, categories={"energy": 200.0, "groceries": 400.0})
    p = month_plan(Plan(savings=300.0), budgets, income=1800.0, spent=500.0, outside_budgets=250.0)
    assert p["income"] == 1800.0
    assert p["available"] == 1500.0
    assert p["allocated"] == 600.0
    assert p["unallocated"] == 900.0
    assert p["total_over_available"] == 200.0  # the total budget leaves no room for the savings target
    assert p["remaining"] == 1000.0
    assert p["outside_budgets"] == 250.0
    assert p["free_remaining"] == 650.0  # 900 unallocated - 250 spent outside the budgets
    # 250 of the 500 spent was inside the budgets, so 350 of the 600 budgeted is still reserved
    assert p["budget_reserved"] == 350.0
    assert p["remaining"] - p["budget_reserved"] == p["free_remaining"]  # the table adds up


def test_month_plan_with_missing_values():
    p = month_plan(Plan(), Budgets(), income=900.0, spent=50.0, outside_budgets=50.0)
    assert p["income"] == 900.0  # known from the data even without a plan
    assert p["available"] is None and p["unallocated"] is None and p["remaining"] is None
    assert p["free_remaining"] is None
    assert p["total_over_available"] is None and p["spent"] == 50.0


def balance_on(series: dict, date: str) -> float:
    return next(p["balance"] for p in series["points"] if p["date"] == date)


def test_balance_anchored_at_the_end_of_the_data():
    # 1800 - 1400 - 200 - 400 + 1800 - 300 - 900 = 400 movement in total
    series = balance_series(frame(), Plan(balance=5000.0, balance_date="2026-09-25", min_balance=4700.0))
    assert balance_on(series, "2026-09-25") == 5000.0
    assert balance_on(series, "2026-09-24") == 5900.0  # before the 900 expense
    assert balance_on(series, "2026-09-20") == 5900.0
    assert balance_on(series, "2026-09-19") == 6200.0
    assert balance_on(series, "2026-08-15") == 6400.0  # 5000 minus every movement after that day
    assert balance_on(series, "2026-09-14") == 4400.0
    assert series["current"] == 5000.0
    assert series["headroom"] == 300.0
    assert series["lowest"] == {"date": "2026-09-03", "balance": 4400.0}


def test_balance_anchored_in_the_middle_and_after_the_data():
    series = balance_series(frame(), Plan(balance=1000.0, balance_date="2026-09-03", min_balance=900.0))
    assert balance_on(series, "2026-09-03") == 1000.0
    assert balance_on(series, "2026-09-02") == 1400.0
    assert balance_on(series, "2026-09-15") == 2800.0
    assert series["current"] == 1600.0  # 1000 + 1800 - 300 - 900

    later = balance_series(frame(), Plan(balance=700.0, balance_date="2026-10-10"))
    assert later["current"] == 700.0 and later["current_date"] == "2026-10-10"
    assert balance_on(later, "2026-09-25") == 700.0
    assert balance_on(later, "2026-09-24") == 1600.0


def test_balance_days_below_the_floor():
    series = balance_series(frame(), Plan(balance=5000.0, balance_date="2026-09-25", min_balance=4500.0))
    assert series["days_below"] == 12  # 3rd to 14th of September, when the balance was 4400
    assert series["headroom"] == 500.0


def test_balance_needs_data_and_an_anchor():
    assert balance_series(frame(), Plan()) is None
    assert balance_series(pd.DataFrame(), Plan(balance=1.0, balance_date="2026-09-01")) is None


from budget.plan import daily_allowance, forecast, month_progress, spending_outside_budgets, typical_spending  # noqa: E402

GROUPS = {"groceries": "variable", "restaurants": "variable", "rent": "fixed", "energy": "fixed", "salary": "income"}


def history(last: str = "2026-10-10") -> pd.DataFrame:
    rows = [
        ("2026-07-01", -650.0, "rent", "fixed"),
        ("2026-07-05", 1800.0, "salary", "income"),
        ("2026-07-10", -400.0, "groceries", "variable"),
        ("2026-07-20", -100.0, "restaurants", "variable"),
        ("2026-08-01", -650.0, "rent", "fixed"),
        ("2026-08-05", 1800.0, "salary", "income"),
        ("2026-08-10", -300.0, "groceries", "variable"),
        ("2026-08-20", -200.0, "restaurants", "variable"),
        ("2026-09-01", -650.0, "rent", "fixed"),
        ("2026-09-05", 1800.0, "salary", "income"),
        ("2026-09-10", -500.0, "groceries", "variable"),
        ("2026-09-15", -60.0, None, None),  # uncategorized expense
        ("2026-10-01", -650.0, "rent", "fixed"),
        ("2026-10-02", 1800.0, "salary", "income"),
        ("2026-10-05", -150.0, "groceries", "variable"),
        ("2026-10-06", -50.0, "restaurants", "variable"),
        (last, -0.01, "groceries", "variable"),  # moves the end of the data
    ]
    df = pd.DataFrame(rows, columns=["date", "amount", "category", "group"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_month_progress_follows_the_data_not_the_clock():
    progress = month_progress(history(), "2026-10")
    assert progress == {"as_of": "2026-10-10", "elapsed": 10, "days_in_month": 31, "days_left": 21}
    assert month_progress(history(), "2026-09") is None  # data continues after it
    assert month_progress(history("2026-10-31"), "2026-10") is None  # the month is complete
    assert month_progress(pd.DataFrame(), "2026-10") is None


def test_daily_allowance():
    progress = month_progress(history(), "2026-10")
    assert daily_allowance(420.0, progress) == 20.0
    assert daily_allowance(-21.0, progress) == -1.0
    assert daily_allowance(None, progress) is None
    assert daily_allowance(100.0, None) is None
    assert daily_allowance(100.0, {**progress, "days_left": 0}) is None


def test_typical_spending_averages_the_last_full_months():
    budgets = Budgets(categories={"restaurants": 80.0, "rent": 650.0})
    result = typical_spending(history(), budgets, "2026-10", GROUPS)
    assert result["months"] == ["2026-07", "2026-08", "2026-09"]
    items = {i["category"]: i for i in result["items"]}
    assert items["groceries"]["average"] == 400.0 and items["groceries"]["suggested"] == 400
    assert items["restaurants"]["average"] == 100.0  # a month without spending counts as zero
    assert items[None]["average"] == 20.0 and items[None]["group"] == "variable"
    assert items["rent"]["group"] == "fixed"
    assert items["groceries"]["this_month"] == 150.01 and items["restaurants"]["this_month"] == 50.0
    assert items["restaurants"]["budget"] == 80.0 and items["groceries"]["budget"] is None
    # categories without a budget first, then by size
    assert [i["category"] for i in result["items"]] == ["groceries", None, "rent", "restaurants"]


def test_typical_spending_needs_full_earlier_months():
    assert typical_spending(history(), Budgets(), "2026-07", GROUPS) == {"months": [], "items": []}
    only_october = history()[history()["date"] >= "2026-10-01"]
    assert typical_spending(only_october, Budgets(), "2026-10", GROUPS)["items"] == []


def test_typical_spending_suggestion_is_rounded_to_five():
    df = pd.DataFrame(
        [("2026-07-01", -1.0, "rent", "fixed"), ("2026-07-10", -123.0, "groceries", "variable"), ("2026-08-15", -5.0, "rent", "fixed"), ("2026-09-15", -1.0, "rent", "fixed")],
        columns=["date", "amount", "category", "group"],
    )
    df["date"] = pd.to_datetime(df["date"])
    items = {i["category"]: i for i in typical_spending(df, Budgets(), "2026-09", GROUPS)["items"]}
    assert items["groceries"]["average"] == 61.5 and items["groceries"]["suggested"] == 60
    assert items["rent"]["suggested"] == 5  # never suggests a zero budget


def test_forecast_extrapolates_variable_spending_only():
    df, plan = history(), Plan(income=1800.0, savings=500.0, min_balance=4000.0)
    progress = month_progress(df, "2026-10")
    balance = {"current": 5000.0}
    result = forecast(df, plan, Budgets(categories={"rent": 650.0}), "2026-10", GROUPS, progress, balance)
    # fixed 650 paid; variable 200.01 so far * 31/10
    assert result["spent"] == 850.01
    assert result["projected_spend"] == pytest.approx(650 + 200.01 * 3.1, abs=0.01)
    assert result["projected_income"] == 1800.0
    assert result["projected_saved"] == pytest.approx(1800 - result["projected_spend"], abs=0.01)
    assert result["saved_vs_target"] == pytest.approx(result["projected_saved"] - 500, abs=0.01)
    assert result["projected_balance"] == pytest.approx(5000 - (result["projected_spend"] - 850.01), abs=0.01)
    assert result["balance_vs_floor"] == pytest.approx(result["projected_balance"] - 4000, abs=0.01)


def test_forecast_adds_unpaid_fixed_budgets_and_expected_income():
    df, progress = history(), month_progress(history(), "2026-10")
    base = forecast(df, Plan(income=1800.0), Budgets(), "2026-10", GROUPS, progress, None)
    more = forecast(df, Plan(income=2000.0), Budgets(categories={"energy": 200.0}), "2026-10", GROUPS, progress, {"current": 5000.0})
    assert more["projected_spend"] == pytest.approx(base["projected_spend"] + 200.0)  # energy not paid yet
    assert more["projected_income"] == 2000.0  # the second salary is still expected
    assert base["projected_balance"] is None and base["saved_vs_target"] is None


def test_forecast_needs_enough_days_of_an_ongoing_month():
    early = history()[history()["date"] <= "2026-10-02"]  # only the first two days of October
    assert forecast(early, Plan(), Budgets(), "2026-10", GROUPS, month_progress(early, "2026-10"), None) is None
    assert forecast(history(), Plan(), Budgets(), "2026-09", GROUPS, None, None) is None


def test_spending_outside_budgets_counts_unbudgeted_and_overspend_only():
    df = history()
    # October: rent 650 (budget 650, fine), groceries 150.01 (budget 100, over by 50.01), restaurants 50 (no budget)
    budgets = Budgets(categories={"groceries": 100.0, "rent": 650.0})
    assert spending_outside_budgets(df, budgets, "2026-10") == 100.01
    # an unspent or fully covered budget adds nothing
    assert spending_outside_budgets(df, Budgets(categories={"groceries": 500.0, "restaurants": 90.0, "rent": 650.0}), "2026-10") == 0.0
    # without budgets everything counts, uncategorized included: groceries 500 + uncategorized 60 + rent 650
    assert spending_outside_budgets(df, Budgets(), "2026-09") == 1210.0
    assert spending_outside_budgets(df, Budgets(), "2025-01") == 0.0


def test_spending_outside_budgets_ignores_income_and_refunds_never_go_below_zero():
    df = history()
    refund = pd.DataFrame([{"date": pd.Timestamp("2026-10-07"), "amount": 400.0, "category": "groceries", "group": "variable"}])
    df = pd.concat([df, refund], ignore_index=True)
    # groceries net is +249.99 (a refund bigger than the spending): counts as zero, not as negative spending
    assert spending_outside_budgets(df, Budgets(categories={"rent": 650.0}), "2026-10") == 50.0  # restaurants only


def test_month_plan_follows_the_real_income_not_the_expected_one():
    budgets = Budgets(categories={"energy": 200.0})
    plan = Plan(income=1800.0, savings=300.0)  # the expected income is only a fallback for projections
    bonus = month_plan(plan, budgets, income=2300.0, spent=0.0, outside_budgets=0.0)
    assert bonus["available"] == 2000.0 and bonus["unallocated"] == 1800.0
    assert bonus["income_pending"] is None  # not in progress
    assert month_plan(plan, budgets, income=1500.0, spent=0.0, outside_budgets=0.0)["available"] == 1200.0


def test_month_plan_reports_income_that_has_not_arrived_in_a_running_month():
    plan = Plan(income=1800.0, savings=300.0)
    early = month_plan(plan, Budgets(), income=0.0, spent=40.0, outside_budgets=40.0, in_progress=True)
    assert early["available"] == -300.0  # nothing has arrived yet, so nothing is available
    assert early["income_pending"] == 1800.0 and early["expected_income"] == 1800.0
    partial = month_plan(plan, Budgets(), income=1000.0, spent=0.0, outside_budgets=0.0, in_progress=True)
    assert partial["income_pending"] == 800.0
    done = month_plan(plan, Budgets(), income=1900.0, spent=0.0, outside_budgets=0.0, in_progress=True)
    assert done["income_pending"] is None  # the expectation is met
    assert month_plan(Plan(savings=300.0), Budgets(), income=0.0, spent=0.0, outside_budgets=0.0, in_progress=True)["income_pending"] is None


from budget.plan import balance_at, month_goal, opening_balance  # noqa: E402


def anchored(start: str | None = "2026-07", **kwargs) -> Plan:
    """history() moves 2839.99 in total, so 8000 at the end of 10 Oct means 5160.01 before July."""
    return Plan(
        balance=8000.0, balance_date="2026-10-10", min_balance=4000.0, savings=500.0, start_month=start, **kwargs
    )


def test_balance_at_and_opening_balance():
    df, plan = history(), anchored()
    assert balance_at(df, plan, pd.Timestamp("2026-10-10")) == 8000.0
    assert balance_at(df, plan, pd.Timestamp("2026-09-30")) == 7050.01
    assert balance_at(df, plan, pd.Timestamp("2026-06-30")) == 5160.01  # before any movement
    assert opening_balance(df, plan, "2026-10") == 7050.01
    assert opening_balance(df, plan, "2026-07") == 5160.01  # the data starts on 1 July
    assert balance_at(df, Plan(), pd.Timestamp("2026-09-30")) is None
    assert opening_balance(pd.DataFrame(), plan, "2026-10") is None


def test_opening_balance_is_unknown_when_the_data_starts_inside_the_month():
    df = history()[history()["date"] >= "2026-07-10"]
    assert opening_balance(df, anchored(), "2026-07") is None
    assert opening_balance(df, anchored(), "2026-08") is not None


def test_goals_form_a_ladder_from_the_minimum_balance():
    df, plan = history(), anchored()
    # the first month aims at 4000 + 500; every later month at the previous goal + 500
    assert [month_goal(df, plan, m)["goal"] for m in ("2026-07", "2026-08", "2026-09", "2026-10")] == [
        4500.0,
        5000.0,
        5500.0,
        6000.0,
    ]
    assert month_goal(df, plan, "2026-10")["source"] == "default"


def test_the_ladder_does_not_depend_on_where_the_month_started():
    # September opened at 6460.01, far above its goal of 5500: the goal still follows the ladder
    goal = month_goal(history(), anchored(), "2026-09")
    assert goal["goal"] == 5500.0 and goal["opening"] == 6460.01 and goal["default"] == 5500.0
    # the alternative starts from where the month began
    assert goal["from_opening"] == 6960.01
    assert month_goal(history(), anchored(), "2026-07")["from_opening"] == 5660.01  # 5160.01 + 500


def test_planning_starts_at_the_start_month():
    df = history()
    assert month_goal(df, anchored("2026-09"), "2026-08") is None  # before the start
    assert month_goal(df, anchored("2026-09"), "2026-09")["goal"] == 4500.0  # the ladder begins here
    assert month_goal(df, anchored("2026-09"), "2026-10")["goal"] == 5000.0
    assert month_goal(df, anchored(None), "2026-10") is None  # no start month, no goals


def test_first_month_without_a_minimum_starts_from_the_opening_balance():
    plan = Plan(balance=8000.0, balance_date="2026-10-10", savings=500.0, start_month="2026-10")
    assert month_goal(history(), plan, "2026-10")["goal"] == 7550.01


def test_no_goal_without_savings_unless_set_by_hand():
    plan = Plan(balance=8000.0, balance_date="2026-10-10", min_balance=4000.0, start_month="2026-10")
    assert month_goal(history(), plan, "2026-10") is None
    custom = Plan(**{**plan.__dict__, "goals": {"2026-10": 6000.0}})
    goal = month_goal(history(), custom, "2026-10")
    assert goal["goal"] == 6000.0 and goal["source"] == "custom" and goal["default"] is None
    assert month_goal(history(), Plan(), "2026-10") is None


def test_a_custom_goal_replaces_the_default_and_the_ladder_continues_from_it():
    plan = anchored(goals={"2026-08": 5800.0})
    aug, sep = month_goal(history(), plan, "2026-08"), month_goal(history(), plan, "2026-09")
    assert aug["goal"] == 5800.0 and aug["source"] == "custom" and aug["default"] == 5000.0
    assert sep["goal"] == 6300.0  # 5800 + 500
    assert month_goal(history(), plan, "2026-07")["goal"] == 4500.0


def test_month_plan_in_balance_mode():
    df, plan = history(), anchored(goals={"2026-10": 8000.0})
    goal = month_goal(df, plan, "2026-10")
    budgets = Budgets(categories={"energy": 200.0})
    p = month_plan(plan, budgets, income=1800.0, spent=900.0, outside_budgets=100.0, goal=goal)
    assert p["mode"] == "balance" and p["opening_balance"] == 7050.01
    assert p["savings"] == 949.99  # the goal minus the opening balance
    assert p["available"] == 850.01  # 7050.01 + 1800 - 8000
    assert p["remaining"] == -49.99  # 850.01 available - 900 spent: this is balance now - goal
    assert p["unallocated"] == 650.01 and p["free_remaining"] == 550.01

    # money moved out of the account (savings, investments) reduces what can be spent
    moved = month_plan(plan, budgets, income=1800.0, spent=0.0, outside_budgets=0.0, goal=goal, transfers_out=300.0)
    assert moved["available"] == 550.01 and moved["transfers_out"] == 300.0

    # the ladder goal of 6000 is below the opening balance, so the month may use some of it
    ladder = month_goal(df, anchored(), "2026-10")
    below = month_plan(anchored(), Budgets(), income=1800.0, spent=0.0, outside_budgets=0.0, goal=ladder)
    assert below["savings"] == -1050.01 and below["available"] == 2850.01

    # a goal that cannot be reached this month
    behind = month_plan(plan, Budgets(), income=1800.0, spent=0.0, outside_budgets=0.0, goal={**goal, "goal": 9000.0})
    assert behind["available"] == pytest.approx(-149.99)


def test_savings_and_typical_spending_ignore_months_before_the_start():
    df = history()
    months = [m["month"] for m in savings_by_month(df, anchored("2026-09"))]
    assert months == ["2026-09", "2026-10"]
    assert [m["month"] for m in savings_by_month(df, Plan())][0] == "2026-07"  # without a start month: all of them
    # September and October as the baseline: only September is a full month before October
    only_september = typical_spending(df, Budgets(plan=anchored("2026-09")), "2026-10", GROUPS)
    assert only_september["months"] == ["2026-09"]
    items = {i["category"]: i for i in only_september["items"]}
    assert items["groceries"]["average"] == 500.0  # not the 400 average of July to September
    # nothing to average yet when the plan starts in the month itself
    assert typical_spending(df, Budgets(plan=anchored("2026-10")), "2026-10", GROUPS) == {"months": [], "items": []}
