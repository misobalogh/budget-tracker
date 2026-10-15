"""Local JSON API for the web UI.

Bind it to 127.0.0.1 only. Transactions are anonymized (private.yaml) right after
loading, so no endpoint can return a private counterparty or message.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from budget.budgets import budget_status, load_budgets, parse_budgets, parse_plan, save_budgets
from budget.categorizer import GROUPS, TEXT_FIELDS, Rule, RuleSet, categorize, load_rules
from budget.plan import (
    balance_series,
    daily_allowance,
    forecast,
    month_goal,
    month_plan,
    month_progress,
    savings_by_month,
    spending_outside_budgets,
    typical_spending,
)
from budget.privacy import PLACEHOLDER, anonymize, load_private_patterns
from budget.report import (
    effective_group,
    load_transactions,
    monthly_category_trend,
    monthly_summary,
    monthly_trend,
)
from budget.rules_editor import add_rule, build_rule, delete_rule, move_rule, suggest_pattern, update_rule

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
PREVIEW_SAMPLE = 20

Sign = Literal["positive", "negative"]
GroupName = Literal["income", "fixed", "variable", "transfer"]


class MatchRequest(BaseModel):
    """Conditions of one rule; all given patterns must match (AND)."""

    counterparty: str | None = None
    message: str | None = None
    raw_category: str | None = None
    sign: Sign | None = None

    def match(self) -> dict[str, str | None]:
        return {field: getattr(self, field) for field in TEXT_FIELDS}


class RulePreviewRequest(MatchRequest):
    category: str | None = None
    new_group: GroupName | None = None
    replace_index: int | None = None  # preview an edit of this rule instead of a new top rule


class RuleWriteRequest(MatchRequest):
    category: str
    new_group: GroupName | None = None


class MoveRequest(BaseModel):
    direction: Literal["up", "down"]


class PlanRequest(BaseModel):
    income: float | None = None
    savings: float | None = None
    min_balance: float | None = None
    balance: float | None = None
    balance_date: str | None = None
    start_month: str | None = None
    goals: dict[str, float] | None = None  # None keeps the goals that are already saved


class GoalRequest(BaseModel):
    month: str
    goal: float | None = None  # None removes the custom goal of that month


class BudgetsRequest(BaseModel):
    total: float | None = None
    groups: dict[str, float] = {}
    categories: dict[str, float] = {}


@dataclass
class Store:
    """In-memory anonymized transactions; rules are re-read on every request."""

    data_dir: Path
    rules_path: Path
    private_path: Path
    budgets_path: Path
    identity: object | None = None  # unlocked secret key when files are encrypted; never leaves memory
    transactions: pd.DataFrame = field(default_factory=pd.DataFrame)

    def reload(self) -> None:
        df = anonymize(
            load_transactions(self.data_dir, self.identity),
            load_private_patterns(self.private_path, self.identity),
        )
        self.transactions = df.reset_index(drop=True)

    def rules(self) -> RuleSet:
        return load_rules(self.rules_path)

    def categorized(self) -> pd.DataFrame:
        return categorize(self.transactions, self.rules())


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.assign(
        id=df.index,
        date=df["date"].dt.strftime("%Y-%m-%d"),
        is_private=df["counterparty"] == PLACEHOLDER,
    )
    if "group" in out:
        out["effective_group"] = effective_group(df)
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")


def _candidate_ruleset(current: RuleSet, rule: Rule, new_group: str | None, replace_index: int | None) -> RuleSet:
    """The ruleset as it would be after adding `rule` on top, or replacing the rule at replace_index."""
    groups = dict(current.groups)
    groups.setdefault(rule.category, new_group or "variable")
    rules = list(current.rules)
    if replace_index is None:
        rules.insert(0, rule)
    elif 0 <= replace_index < len(rules):
        rules[replace_index] = rule
    else:
        raise ValueError(f"rule index {replace_index} is out of range")
    return RuleSet(groups=groups, rules=rules)


def create_app(
    data_dir: str | Path,
    rules_path: str | Path,
    private_path: str | Path,
    static_dir: str | Path | None = None,
    *,
    budgets_path: str | Path = "budgets.yaml",
    identity: object | None = None,
) -> FastAPI:
    store = Store(Path(data_dir), Path(rules_path), Path(private_path), Path(budgets_path), identity)
    store.reload()

    app = FastAPI(title="Budget tracker", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/meta")
    def meta() -> dict:
        df = store.transactions
        ruleset = store.rules()
        counts = df.groupby(df["date"].dt.to_period("M").astype(str)).size() if not df.empty else {}
        months = [
            {
                "month": row["month"],
                "count": int(counts[row["month"]]),
                "partial": bool(row["partial"]),
                "income": row["income"],
                "expenses": round(row["fixed"] + row["variable"], 2),
            }
            for row in monthly_trend(store.categorized()).to_dict(orient="records")
        ]
        return {
            "count": len(df),
            "date_from": None if df.empty else f"{df['date'].min():%Y-%m-%d}",
            "date_to": None if df.empty else f"{df['date'].max():%Y-%m-%d}",
            "months": months,
            "groups": list(GROUPS),
            "categories": [{"name": name, "group": group} for name, group in sorted(ruleset.groups.items())],
        }

    @app.get("/api/summary")
    def summary(month: str) -> dict:
        df = store.categorized()
        s = monthly_summary(df, month)
        by_category = [
            {"category": name, "group": store.rules().groups[name], "amount": float(amount)}
            for name, amount in s.by_category.items()
        ]
        return {
            "month": s.month,
            "income": s.income,
            "fixed": s.fixed,
            "variable": s.variable,
            "transfer": s.transfer,
            "balance": s.balance,
            "partial": s.partial,
            "by_category": by_category,
            "uncategorized_count": len(s.uncategorized),
            "uncategorized_income": round(float(s.uncategorized["amount"].clip(lower=0).sum()), 2),
            "uncategorized_expenses": round(float(s.uncategorized["amount"].clip(upper=0).sum()), 2),
        }

    @app.get("/api/trend")
    def trend() -> dict:
        df = store.categorized()
        return {
            "months": monthly_trend(df).to_dict(orient="records"),
            "categories": monthly_category_trend(df).to_dict(orient="records"),
        }

    @app.get("/api/transactions")
    def transactions(
        month: str | None = None,
        group: str | None = None,
        category: str | None = None,
        uncategorized: bool = False,
        q: str | None = None,
    ) -> dict:
        df = store.categorized()
        if month:
            df = df[df["date"].dt.to_period("M") == pd.Period(month, freq="M")]
        if group:
            df = df[effective_group(df) == group]
        if category:
            df = df[df["category"] == category]
        if uncategorized:
            df = df[df["category"].isna()]
        if q:
            needle = q.lower()
            hay = (df["counterparty"] + " " + df["message"]).str.lower()
            df = df[hay.str.contains(needle, regex=False)]
        df = df.sort_values("date", ascending=False, kind="stable")
        items = _records(df)
        for item in items:
            item["suggested_pattern"] = None if item["is_private"] else suggest_pattern(item["counterparty"])
        return {"items": items, "total": round(float(df["amount"].sum()), 2), "count": len(df)}

    @app.get("/api/rules")
    def rules_list() -> dict:
        ruleset = store.rules()
        df = store.categorized()
        wins = df["rule_index"].dropna().astype(int).value_counts().to_dict()
        rows = [row for _, row in store.transactions.iterrows()]
        return {
            "rules": [
                {
                    "index": i,
                    "category": rule.category,
                    "group": ruleset.groups[rule.category],
                    "match": {field: pattern.pattern for field, pattern in rule.patterns.items()},
                    "sign": rule.sign,
                    "wins": int(wins.get(i, 0)),
                    "matches": sum(rule.matches(row) for row in rows),
                }
                for i, rule in enumerate(ruleset.rules)
            ]
        }

    @app.post("/api/rules/preview")
    def rules_preview(body: RulePreviewRequest) -> dict:
        """Which transactions would change category if this rule were saved (as new or as an edit)."""
        df = store.categorized()
        rule = build_rule(body.match(), body.sign, body.category or "_preview")
        matches = sum(rule.matches(row) for _, row in df.iterrows())
        if not body.category:
            return {"count": matches, "changed": 0, "moves": [], "sample": []}
        candidate = _candidate_ruleset(store.rules(), rule, body.new_group, body.replace_index)
        after = categorize(store.transactions, candidate)
        before_cat, after_cat = df["category"].fillna(""), after["category"].fillna("")
        changed = df[before_cat != after_cat].assign(new_category=after["category"])
        moves = (
            pd.DataFrame({"from": df.loc[changed.index, "category"], "to": changed["new_category"]})
            .fillna("")
            .value_counts()
            .reset_index(name="count")
        )
        return {
            "count": matches,
            "changed": len(changed),
            "moves": [
                {"from": m["from"] or None, "to": m["to"] or None, "count": int(m["count"])}
                for m in moves.to_dict(orient="records")
            ],
            "sample": _records(changed.sort_values("date", ascending=False).head(PREVIEW_SAMPLE)),
        }

    @app.post("/api/rules")
    def rules_create(body: RuleWriteRequest) -> dict:
        add_rule(store.rules_path, body.category, body.match(), body.sign, body.new_group)
        return {"ok": True}

    @app.put("/api/rules/{index}")
    def rules_update(index: int, body: RuleWriteRequest) -> dict:
        update_rule(store.rules_path, index, body.category, body.match(), body.sign, body.new_group)
        return {"ok": True}

    @app.delete("/api/rules/{index}")
    def rules_delete(index: int) -> dict:
        delete_rule(store.rules_path, index)
        return {"ok": True}

    @app.post("/api/rules/{index}/move")
    def rules_move(index: int, body: MoveRequest) -> dict:
        move_rule(store.rules_path, index, body.direction)
        return {"ok": True}

    @app.get("/api/budgets")
    def budgets_get(month: str) -> dict:
        budgets = load_budgets(store.budgets_path)
        return {
            "month": month,
            "config": budgets.as_dict(),
            "items": budget_status(store.categorized(), budgets, month, store.rules().groups),
        }

    @app.put("/api/budgets")
    def budgets_put(body: BudgetsRequest) -> dict:
        existing = load_budgets(store.budgets_path)
        save_budgets(store.budgets_path, replace(parse_budgets(body.model_dump()), plan=existing.plan))
        return {"ok": True}

    @app.get("/api/plan")
    def plan_get(month: str) -> dict:
        budgets = load_budgets(store.budgets_path)
        df = store.categorized()
        s = monthly_summary(df, month)
        groups = store.rules().groups
        outside = spending_outside_budgets(df, budgets, month)
        progress = month_progress(df, month)
        goal = month_goal(df, budgets.plan, month)
        this_month = month_plan(
            budgets.plan,
            budgets,
            s.income,
            -(s.fixed + s.variable),
            outside,
            in_progress=progress is not None,
            goal=goal,
            transfers_out=-s.transfer,
        )
        balance = balance_series(df, budgets.plan)
        projected = forecast(df, budgets.plan, budgets, month, groups, progress, balance)
        if projected is not None:
            end = projected["projected_balance"]
            projected["balance_vs_goal"] = None if end is None or goal is None else round(end - goal["goal"], 2)
        return {
            "plan": budgets.plan.as_dict(),
            "month": this_month,
            "progress": None
            if progress is None
            else {**progress, "per_day": daily_allowance(this_month["free_remaining"], progress)},
            "forecast": projected,
            "typical": typical_spending(df, budgets, month, groups),
            "savings": savings_by_month(df, budgets.plan),
            "balance": balance,
        }

    @app.put("/api/plan")
    def plan_put(body: PlanRequest) -> dict:
        existing = load_budgets(store.budgets_path)
        plan = parse_plan(body.model_dump())
        if body.goals is None:
            plan = replace(plan, goals=existing.plan.goals)
        save_budgets(store.budgets_path, replace(existing, plan=plan))
        return {"ok": True}

    @app.put("/api/plan/goal")
    def plan_goal_put(body: GoalRequest) -> dict:
        existing = load_budgets(store.budgets_path)
        goals = dict(existing.plan.goals)
        if body.goal is None:
            goals.pop(body.month, None)
        else:
            goals[body.month] = body.goal
        plan = parse_plan({**existing.plan.as_dict(), "goals": goals})
        save_budgets(store.budgets_path, replace(existing, plan=plan))
        return {"ok": True}

    @app.post("/api/reload")
    def reload() -> dict:
        store.reload()
        store.rules()  # surface a broken rules.yaml right away
        return {"ok": True, "count": len(store.transactions)}

    @app.get("/api/{path:path}")
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail="not found")

    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app
