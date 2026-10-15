"""Monthly spending limits (budgets) and how much of each is used.

budgets.yaml:
    total: 2000          # all expenses (fixed + variable) per month
    groups:
      variable: 1500     # fixed | variable
    categories:
      groceries: 400     # any category from rules.yaml

    plan:
      income: 1800       # expected monthly net income
      savings: 300       # target to save each month
      min_balance: 4000  # the account balance should stay above this
      balance: 5200.0    # known balance ...
      balance_date: '2026-10-02'  # ... at the end of this day
      start_month: '2026-10'  # plan from this month on; earlier months are ignored
      goals:             # optional month-end balance goals that replace the default
        '2026-11': 5000

Limits are in EUR and apply to every month independently (no carry-over).
Spending is net: refunds in a category reduce what counts as spent.
"""

import datetime
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from budget.fileio import write_text_atomic
from budget.report import effective_group

BUDGET_GROUPS = ("fixed", "variable")
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
WARNING_RATIO = 0.8
HEADER = (
    "# Monthly spending limits in EUR, managed from the UI (comments are not kept).\n"
    "# total: all expenses; groups: fixed | variable; categories: names from rules.yaml;\n"
    "# plan: expected income, savings target, minimum balance and one known balance.\n"
)


@dataclass(frozen=True)
class Plan:
    """Monthly plan: expected income, savings target and the account balance to keep."""

    income: float | None = None
    savings: float | None = None
    min_balance: float | None = None
    balance: float | None = None
    balance_date: str | None = None  # ISO date; the balance is valid at the end of that day
    start_month: str | None = None  # "YYYY-MM": planning starts here, earlier months are not used
    goals: dict[str, float] = field(default_factory=dict)  # "YYYY-MM" -> balance wanted at the end of that month

    def is_empty(self) -> bool:
        return all(v is None for k, v in self.as_dict().items() if k != "goals") and not self.goals

    def as_dict(self) -> dict:
        return {
            "income": self.income,
            "savings": self.savings,
            "min_balance": self.min_balance,
            "balance": self.balance,
            "balance_date": self.balance_date,
            "start_month": self.start_month,
            "goals": dict(self.goals),
        }


@dataclass(frozen=True)
class Budgets:
    total: float | None = None
    groups: dict[str, float] = field(default_factory=dict)
    categories: dict[str, float] = field(default_factory=dict)
    plan: Plan = field(default_factory=Plan)

    def is_empty(self) -> bool:
        return self.total is None and not self.groups and not self.categories and self.plan.is_empty()

    def as_dict(self) -> dict:
        """The limits only; the plan is managed separately."""
        return {"total": self.total, "groups": dict(self.groups), "categories": dict(self.categories)}


def _limit(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what}: limit must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{what}: limit must be greater than zero")
    return round(float(value), 2)


def _amount(value: object, what: str, *, minimum_exclusive: float | None = 0) -> float:
    """A finite number, greater than `minimum_exclusive` when given (None allows any number)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number")
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ValueError(f"{what} must be greater than {minimum_exclusive:g}")
    return round(float(value), 2)


def parse_plan(data: dict | None) -> Plan:
    """Validate a plan mapping; balance and balance_date must be given together."""
    data = data or {}
    unknown = set(data) - {"income", "savings", "min_balance", "balance", "balance_date", "start_month", "goals"}
    if unknown:
        raise ValueError(f"plan: unknown key(s): {', '.join(sorted(unknown))}")

    def optional(key: str, **kwargs: float | None) -> float | None:
        return None if data.get(key) is None else _amount(data[key], f"plan {key.replace('_', ' ')}", **kwargs)

    balance = optional("balance", minimum_exclusive=None)
    raw_date = data.get("balance_date")
    if isinstance(raw_date, datetime.date):  # YAML turns unquoted dates into date objects
        raw_date = raw_date.isoformat()
    if (balance is None) != (raw_date is None):
        raise ValueError("plan: balance and balance date must be given together")
    if raw_date is not None:
        try:
            raw_date = datetime.date.fromisoformat(str(raw_date)).isoformat()
        except ValueError:
            raise ValueError("plan: balance date must be a date like 2026-10-02") from None
    start_month = data.get("start_month")
    if start_month is not None and not (isinstance(start_month, str) and MONTH_RE.fullmatch(start_month)):
        raise ValueError(f"plan: start month must look like 2026-10, got {start_month!r}")
    goals = {}
    for month, value in (data.get("goals") or {}).items():
        if not isinstance(month, str) or not MONTH_RE.fullmatch(month):
            raise ValueError(f"plan: goal month must look like 2026-11, got {month!r}")
        goals[month] = _amount(value, f"plan goal for {month}")
    return Plan(
        income=optional("income"),
        savings=optional("savings"),
        min_balance=optional("min_balance", minimum_exclusive=-1),
        balance=balance,
        balance_date=raw_date,
        start_month=start_month,
        goals=dict(sorted(goals.items())),
    )


def parse_budgets(data: dict | None) -> Budgets:
    """Validate a budgets mapping (as loaded from YAML or sent by the UI)."""
    data = data or {}
    unknown = set(data) - {"total", "groups", "categories", "plan"}
    if unknown:
        raise ValueError(f"unknown key(s): {', '.join(sorted(unknown))}")
    total = data.get("total")
    groups = data.get("groups") or {}
    categories = data.get("categories") or {}
    for name in groups:
        if name not in BUDGET_GROUPS:
            raise ValueError(f"group '{name}': budgets can only be set for {', '.join(BUDGET_GROUPS)}")
    for name in categories:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("category names must be non-empty text")
    return Budgets(
        total=None if total is None else _limit(total, "total"),
        groups={name: _limit(v, f"group '{name}'") for name, v in groups.items()},
        categories={name: _limit(v, f"category '{name}'") for name, v in categories.items()},
        plan=parse_plan(data.get("plan")),
    )


def load_budgets(path: str | Path) -> Budgets:
    """Read budgets.yaml; a missing file means no budgets."""
    path = Path(path)
    if not path.exists():
        return Budgets()
    with open(path, encoding="utf-8") as f:
        return parse_budgets(yaml.safe_load(f))


def save_budgets(path: str | Path, budgets: Budgets) -> None:
    """Validate and write budgets.yaml atomically."""
    budgets = parse_budgets({**budgets.as_dict(), "plan": budgets.plan.as_dict()})
    data: dict = {}
    if budgets.total is not None:
        data["total"] = budgets.total
    if budgets.groups:
        data["groups"] = dict(sorted(budgets.groups.items()))
    if budgets.categories:
        data["categories"] = dict(sorted(budgets.categories.items()))
    if not budgets.plan.is_empty():
        data["plan"] = {k: v for k, v in budgets.plan.as_dict().items() if v not in (None, {})}
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False) if data else "{}\n"
    write_text_atomic(Path(path), HEADER + body)


def _status(spent: float, limit: float, warn: bool = True) -> str:
    if spent > limit:
        return "over"
    return "warning" if warn and spent >= limit * WARNING_RATIO else "ok"


def budget_status(df: pd.DataFrame, budgets: Budgets, month: str, category_groups: dict[str, str]) -> list[dict]:
    """Usage of every budget in `month`. df must be categorized (category and group columns).

    category_groups maps every known category to its group. A fixed expense that is paid on
    schedule uses up its whole limit by design, so budgets of fixed expenses never warn
    before the limit is exceeded (status is "ok" or "over").

    Items: total first, then groups, then categories (largest limit first). `spent` is never
    negative; `remaining` is negative when over the limit.
    """
    period = pd.Period(month, freq="M")
    rows = df[df["date"].dt.to_period("M") == period]
    group = effective_group(rows)

    def item(kind: str, key: str | None, limit: float, spent: float, known: bool = True, warn: bool = True) -> dict:
        spent = max(0.0, round(float(spent), 2))
        return {
            "kind": kind,
            "key": key,
            "limit": limit,
            "spent": spent,
            "remaining": round(limit - spent, 2),
            "ratio": round(spent / limit, 4),
            "status": _status(spent, limit, warn),
            "known": known,
        }

    items = []
    if budgets.total is not None:
        items.append(item("total", None, budgets.total, -rows[group.isin(BUDGET_GROUPS)]["amount"].sum()))
    for name in BUDGET_GROUPS:
        if name in budgets.groups:
            items.append(item("group", name, budgets.groups[name], -rows[group == name]["amount"].sum(), warn=name != "fixed"))
    by_category = [
        item(
            "category",
            name,
            limit,
            -rows[rows["category"] == name]["amount"].sum(),
            known=name in category_groups,
            warn=category_groups.get(name) != "fixed",
        )
        for name, limit in budgets.categories.items()
    ]
    return items + sorted(by_category, key=lambda i: (-i["limit"], i["key"]))
