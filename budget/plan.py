"""Plan calculations: savings per month, the monthly spending plan and the account balance over time.

Saved in a month = income - expenses (fixed + variable). Money moved to a savings or
investment account is a `transfer`, which is not an expense, so it counts as saved.
"""

import pandas as pd

from budget.budgets import BUDGET_GROUPS, Budgets, Plan
from budget.report import effective_group, is_partial_month, monthly_trend

TYPICAL_MONTHS = 3  # how many full months the "typical spending" is averaged over
MIN_FORECAST_DAYS = 3  # a forecast from fewer days of data would be mostly noise
ROUND_TO = 5  # suggested budgets are rounded to a multiple of this


def savings_by_month(df: pd.DataFrame, plan: Plan) -> list[dict]:
    """Per month: income, expenses, saved, and whether the savings target was met."""
    if df.empty:
        return []
    out = []
    for row in monthly_trend(df).to_dict(orient="records"):
        if plan.start_month and row["month"] < plan.start_month:
            continue
        saved = round(row["income"] + row["fixed"] + row["variable"], 2)
        target = plan.savings
        out.append(
            {
                "month": row["month"],
                "income": row["income"],
                "expenses": round(-(row["fixed"] + row["variable"]), 2),
                "saved": saved,
                "target": target,
                "difference": None if target is None else round(saved - target, 2),
                "met": None if target is None else saved >= target,
            }
        )
    return out


def spending_outside_budgets(df: pd.DataFrame, budgets: Budgets, month: str) -> float:
    """Spending of `month` that is not covered by a category budget.

    That is everything in categories without a budget (uncategorized included), plus whatever a
    budgeted category spent beyond its limit. Money inside a budget is already reserved in the plan,
    so only this part eats into the unallocated money. Refunds reduce a category, never below zero.
    """
    period = pd.Period(month, freq="M")
    rows = df[df["date"].dt.to_period("M") == period]
    expenses = rows[effective_group(rows).isin(BUDGET_GROUPS)]
    net = -expenses.groupby(expenses["category"].fillna(""))["amount"].sum()
    outside = 0.0
    for name, spent in net.items():
        spent = max(0.0, float(spent))
        limit = budgets.categories.get(name) if name else None
        outside += spent if limit is None else max(0.0, spent - limit)
    return round(outside, 2)


def balance_at(df: pd.DataFrame, plan: Plan, day: pd.Timestamp) -> float | None:
    """The account balance at the end of `day`, from the known balance and the movements in between."""
    if plan.balance is None or plan.balance_date is None:
        return None

    def moved(until: pd.Timestamp) -> float:
        return float(df.loc[df["date"] <= until, "amount"].sum())

    return round(plan.balance + moved(day) - moved(pd.Timestamp(plan.balance_date)), 2)


def opening_balance(df: pd.DataFrame, plan: Plan, month: str) -> float | None:
    """The balance at the start of `month`; None when it cannot be known.

    That is the case without a known balance, and when the data starts after the month began
    (movements before the first export are missing, so the opening balance would be a guess).
    """
    if df.empty:
        return None
    start = pd.Period(month, freq="M").start_time.normalize()
    if df["date"].min() > start:
        return None
    return balance_at(df, plan, start - pd.Timedelta(days=1))


def month_goal(df: pd.DataFrame, plan: Plan, month: str) -> dict | None:
    """The balance to end `month` with; None before the planning start, without an opening balance or a basis.

    Goals form a ladder: the first planned month aims at the minimum balance plus the savings target,
    and every later month at the previous goal plus the savings target. A month that falls short is
    therefore made up for in the next one. A goal set by hand (plan.goals) replaces the default, and the
    ladder continues from it. `from_opening` is the alternative that starts from where the month began:
    the opening balance (at least the minimum balance) plus the savings target.
    """
    if plan.start_month is None or month < plan.start_month:
        return None
    opening = opening_balance(df, plan, month)
    if opening is None:
        return None
    floor, savings = plan.min_balance, plan.savings
    base = floor if floor is not None else opening
    previous = month_goal(df, plan, str(pd.Period(month, freq="M") - 1))
    if savings is None:
        default = from_opening = None
    else:
        default = round((base if previous is None else previous["goal"]) + savings, 2)
        from_opening = round(max(opening, base) + savings, 2)
    custom = plan.goals.get(month)
    goal = default if custom is None else custom
    if goal is None:
        return None
    return {
        "goal": goal,
        "source": "default" if custom is None else "custom",
        "opening": opening,
        "default": default,
        "from_opening": from_opening,
    }


def month_plan(
    plan: Plan,
    budgets: Budgets,
    income: float,
    spent: float,
    outside_budgets: float,
    in_progress: bool = False,
    goal: dict | None = None,
    transfers_out: float = 0.0,
) -> dict:
    """The plan for one month: what is left to spend, and how it is allocated.

    `income` is the income that actually arrived in the month, so the plan follows reality rather than
    a fixed amount. `spent` is the net spending (fixed + variable) so far and `outside_budgets` the part
    of it not covered by a category budget (see spending_outside_budgets). free_remaining is the
    unallocated money still unused (negative once used up). For a month in progress, income_pending is
    the expected income (plan.income, optional) that has not arrived yet.

    With a `goal` (see month_goal) the plan is based on the account balance: what may be spent is the
    opening balance plus the income, minus money moved out of the account (`transfers_out`), minus the
    balance wanted at the end of the month. Without one it falls back to income minus the savings target.
    Values that cannot be computed are None.
    """
    if goal is not None:
        savings = round(goal["goal"] - goal["opening"], 2)  # what the goal means for this month
        available = round(goal["opening"] + income - transfers_out - goal["goal"], 2)
    else:
        savings = plan.savings
        available = None if savings is None else round(income - savings, 2)
    expected = plan.income
    pending = round(expected - income, 2) if in_progress and expected is not None and expected > income else None
    allocated = round(sum(budgets.categories.values()), 2)
    return {
        "mode": "balance" if goal is not None else "income",
        "goal": goal,
        "opening_balance": None if goal is None else goal["opening"],
        "transfers_out": round(transfers_out, 2),
        "income": round(income, 2),
        "expected_income": expected,
        "income_pending": pending,
        "savings": savings,
        "available": available,
        "allocated": allocated,
        "unallocated": None if available is None else round(available - allocated, 2),
        "total_budget": budgets.total,
        "total_over_available": (
            None if available is None or budgets.total is None else round(max(0.0, budgets.total - available), 2)
        ),
        "spent": round(spent, 2),
        "remaining": None if available is None else round(available - spent, 2),
        "outside_budgets": round(outside_budgets, 2),
        "free_remaining": None if available is None else round(available - allocated - outside_budgets, 2),
        # the part of the category budgets that is still unused and therefore kept free for them
        "budget_reserved": None if available is None else round(allocated - (spent - outside_budgets), 2),
    }


def balance_series(df: pd.DataFrame, plan: Plan) -> dict | None:
    """End-of-day account balance for every day of the data, derived from one known balance.

    The balance at the end of `plan.balance_date` is the anchor; earlier and later days follow from
    the movements (all of them, transfers included). It is only as complete as the exports are.
    Returns None without data or without a known balance.
    """
    if df.empty or plan.balance is None or plan.balance_date is None:
        return None
    anchor_date = pd.Timestamp(plan.balance_date)
    days = pd.date_range(min(df["date"].min(), anchor_date), max(df["date"].max(), anchor_date))
    cumulative = df.groupby("date")["amount"].sum().reindex(days, fill_value=0.0).cumsum()
    balance = (plan.balance + cumulative - cumulative.loc[anchor_date]).round(2)

    lowest_day = balance.idxmin()
    current = float(balance.iloc[-1])
    floor = plan.min_balance
    return {
        "points": [{"date": f"{d:%Y-%m-%d}", "balance": float(v)} for d, v in balance.items()],
        "current": current,
        "current_date": f"{days[-1]:%Y-%m-%d}",
        "min_balance": floor,
        "headroom": None if floor is None else round(current - floor, 2),
        "lowest": {"date": f"{lowest_day:%Y-%m-%d}", "balance": float(balance.loc[lowest_day])},
        "days_below": None if floor is None else int((balance < floor).sum()),
    }


def month_progress(df: pd.DataFrame, month: str) -> dict | None:
    """How far the month is, judged by the data (not the clock); None unless the month is in progress.

    A month is in progress when the newest transaction lies inside it and before its last day.
    """
    if df.empty:
        return None
    period = pd.Period(month, freq="M")
    last = df["date"].max()
    if last.to_period("M") != period or last >= period.end_time.normalize():
        return None
    return {
        "as_of": f"{last:%Y-%m-%d}",
        "elapsed": last.day,
        "days_in_month": period.days_in_month,
        "days_left": period.days_in_month - last.day,
    }


def daily_allowance(free_remaining: float | None, progress: dict | None) -> float | None:
    """What can be spent per remaining day from the free (unallocated) money; negative when it is used up."""
    if free_remaining is None or progress is None or progress["days_left"] <= 0:
        return None
    return round(free_remaining / progress["days_left"], 2)


def _spent(rows: pd.DataFrame, mask: pd.Series) -> float:
    """Net spending of the selected rows (refunds reduce it), never negative."""
    return max(0.0, round(float(-rows[mask]["amount"].sum()), 2))


def typical_spending(df: pd.DataFrame, budgets: Budgets, month: str, category_groups: dict[str, str]) -> dict:
    """Average monthly spending per category over the last full months before `month`.

    Items are categories (and uncategorized, with category None) that cost money, with the average,
    a suggested budget, spending in `month` and the current budget. Categories without a budget come first.
    """
    period = pd.Period(month, freq="M")
    months = sorted(df["date"].dt.to_period("M").unique()) if not df.empty else []
    start = budgets.plan.start_month
    window = [
        m for m in months if m < period and not is_partial_month(df, m) and (start is None or str(m) >= start)
    ][-TYPICAL_MONTHS:]
    if not window:
        return {"months": [], "items": []}

    def expenses(rows: pd.DataFrame) -> pd.DataFrame:
        return rows[effective_group(rows).isin(BUDGET_GROUPS)]

    past = expenses(df[df["date"].dt.to_period("M").isin(window)])
    current = expenses(df[df["date"].dt.to_period("M") == period])
    totals = -past.groupby(past["category"].fillna(""))["amount"].sum()

    items = []
    for name, total in totals.items():
        average = round(float(total) / len(window), 2)
        if average <= 0:
            continue
        category = name or None
        in_month = _spent(current, current["category"].fillna("") == name)
        items.append(
            {
                "category": category,
                "group": category_groups.get(category, "variable") if category else "variable",
                "average": average,
                "suggested": max(ROUND_TO, int(ROUND_TO * round(average / ROUND_TO))),
                "this_month": in_month,
                "budget": budgets.categories.get(category) if category else None,
            }
        )
    items.sort(key=lambda i: (i["budget"] is not None, -i["average"]))
    return {"months": [str(m) for m in window], "items": items}


def forecast(
    df: pd.DataFrame,
    plan: Plan,
    budgets: Budgets,
    month: str,
    category_groups: dict[str, str],
    progress: dict | None,
    balance: dict | None,
) -> dict | None:
    """Where an in-progress month is heading, if spending continues at the pace so far.

    Variable spending is extrapolated linearly; fixed spending is what has been paid plus the
    fixed category budgets that are still unpaid. Transfers are left out. None when the month is
    not in progress or fewer than MIN_FORECAST_DAYS days are covered.
    """
    if progress is None or progress["elapsed"] < MIN_FORECAST_DAYS:
        return None
    period = pd.Period(month, freq="M")
    rows = df[df["date"].dt.to_period("M") == period]
    group = effective_group(rows)

    fixed = _spent(rows, group == "fixed")
    variable = _spent(rows, group == "variable")
    unpaid_fixed = sum(
        max(0.0, limit - _spent(rows, rows["category"] == name))
        for name, limit in budgets.categories.items()
        if category_groups.get(name) == "fixed"
    )
    spent = fixed + variable
    projected_spend = round(fixed + unpaid_fixed + variable * progress["days_in_month"] / progress["elapsed"], 2)

    income_so_far = round(float(rows[group == "income"]["amount"].sum()), 2)
    projected_income = max(plan.income or 0.0, income_so_far)
    projected_saved = round(projected_income - projected_spend, 2)
    projected_balance = (
        None
        if balance is None
        else round(balance["current"] + (projected_income - income_so_far) - (projected_spend - spent), 2)
    )
    floor = plan.min_balance
    return {
        "spent": round(spent, 2),
        "projected_spend": projected_spend,
        "projected_income": round(projected_income, 2),
        "projected_saved": projected_saved,
        "saved_vs_target": None if plan.savings is None else round(projected_saved - plan.savings, 2),
        "projected_balance": projected_balance,
        "balance_vs_floor": None if projected_balance is None or floor is None else round(projected_balance - floor, 2),
    }
