"""Loading of exports and the monthly summary."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from budget.crypto import ENCRYPTED_SUFFIX
from budget.parsers import NORMALIZED_COLUMNS
from budget.parsers.csob import parse_csob


def load_transactions(data_dir: str | Path, identity: object | None = None) -> pd.DataFrame:
    """Parse all *.csv and encrypted *.csv.age in data_dir and merge overlapping exports.

    A transaction present in several files is kept once, while identical
    transactions within a single file (e.g. two equal coffees) are all kept:
    each file contributes the n-th occurrence of a row, and only the n-th
    occurrences are de-duplicated across files.
    """
    data_dir = Path(data_dir)
    files = sorted([*data_dir.glob("*.csv"), *data_dir.glob(f"*.csv{ENCRYPTED_SUFFIX}")])
    if not files:
        raise ValueError(f"no *.csv or *.csv.age files found in {data_dir}")
    frames = []
    for path in files:
        df = parse_csob(path, identity)
        df["_occurrence"] = df.groupby(NORMALIZED_COLUMNS, dropna=False).cumcount()
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True).drop_duplicates()
    return merged.drop(columns="_occurrence").sort_values("date", kind="stable").reset_index(drop=True)


@dataclass(frozen=True)
class MonthlySummary:
    month: str
    income: float
    fixed: float
    variable: float
    transfer: float
    by_category: pd.Series
    uncategorized: pd.DataFrame
    partial: bool = False

    @property
    def balance(self) -> float:
        return round(self.income + self.fixed + self.variable, 2)


GROUP_ORDER = ["income", "fixed", "variable", "transfer"]


def effective_group(df: pd.DataFrame) -> pd.Series:
    """Rule group, or for uncategorized rows: income if positive, else variable."""
    fallback = df["amount"].map(lambda a: "income" if a > 0 else "variable")
    return df["group"].where(df["group"].notna(), fallback)


def is_partial_month(df: pd.DataFrame, period: pd.Period) -> bool:
    """True when the data does not cover the whole month (export starts or ends inside it)."""
    if df.empty:
        return True
    first, last = df["date"].min(), df["date"].max()
    return first > period.start_time.normalize() or last < period.end_time.normalize()


def monthly_summary(df: pd.DataFrame, month: str) -> MonthlySummary:
    """Summarize a categorized DataFrame for month 'YYYY-MM'.

    Uncategorized transactions still count: positive ones as income,
    negative ones as variable. Expenses are negative numbers.
    """
    period = pd.Period(month, freq="M")
    rows = df[df["date"].dt.to_period("M") == period]
    totals = rows["amount"].groupby(effective_group(rows)).sum()

    def total(group: str) -> float:
        return round(float(totals.get(group, 0.0)), 2)

    categorized = rows[rows["category"].notna()]
    by_category = categorized.groupby("category")["amount"].sum().round(2).sort_values()
    uncategorized = rows[rows["category"].isna()][["date", "amount", "counterparty", "message", "raw_category"]]
    return MonthlySummary(
        month=str(period),
        income=total("income"),
        fixed=total("fixed"),
        variable=total("variable"),
        transfer=total("transfer"),
        by_category=by_category,
        uncategorized=uncategorized.reset_index(drop=True),
        partial=is_partial_month(df, period),
    )


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Per-month totals: columns month, income, fixed, variable, transfer, balance, partial."""
    if df.empty:
        return pd.DataFrame(columns=["month", *GROUP_ORDER, "balance", "partial"])
    months = df["date"].dt.to_period("M")
    table = df["amount"].groupby([months, effective_group(df)]).sum().unstack(fill_value=0.0)
    table = table.reindex(columns=GROUP_ORDER, fill_value=0.0).round(2)
    table["balance"] = (table["income"] + table["fixed"] + table["variable"]).round(2)
    table["partial"] = [is_partial_month(df, period) for period in table.index]
    table.index = table.index.astype(str)
    return table.rename_axis("month").reset_index()


def monthly_category_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Long format: month, category, group, amount (categorized rows only)."""
    rows = df[df["category"].notna()]
    out = rows.groupby([rows["date"].dt.to_period("M").astype(str), "category", "group"])["amount"].sum().round(2)
    return out.rename_axis(["month", "category", "group"]).reset_index()


def format_summary(summary: MonthlySummary) -> str:
    lines = [
        f"Monthly summary {summary.month}",
        "",
        f"  income    {summary.income:>12.2f}",
        f"  fixed     {summary.fixed:>12.2f}",
        f"  variable  {summary.variable:>12.2f}",
        f"  balance   {summary.balance:>12.2f}",
        f"  (transfer {summary.transfer:>12.2f}, not counted)",
        *(["", "  NOTE: data does not cover the whole month"] if summary.partial else []),
        "",
        "By category:",
    ]
    lines += [f"  {name:<20} {amount:>12.2f}" for name, amount in summary.by_category.items()] or ["  (none)"]
    lines += ["", f"Uncategorized ({len(summary.uncategorized)}):"]
    for row in summary.uncategorized.itertuples():
        lines.append(
            f"  {row.date:%Y-%m-%d} {row.amount:>10.2f}  {row.counterparty[:30]:<30}  "
            f"{row.raw_category[:22]:<22}  {row.message[:60]}"
        )
    if summary.uncategorized.empty:
        lines.append("  (none)")
    return "\n".join(lines)


def counterparty_stats(df: pd.DataFrame, month: str | None = None, exclude_types: list[str] | None = None) -> pd.DataFrame:
    """Unique (counterparty, raw_category) pairs with occurrence counts, most frequent first.

    Deliberately contains no amounts or messages, so it is safe to share.
    """
    rows = df
    if month is not None:
        rows = rows[rows["date"].dt.to_period("M") == pd.Period(month, freq="M")]
    if exclude_types:
        excluded = {t.lower() for t in exclude_types}
        rows = rows[~rows["raw_category"].str.lower().isin(excluded)]
    stats = rows.groupby(["counterparty", "raw_category"]).size().rename("count").reset_index()
    return stats.sort_values(["count", "counterparty"], ascending=[False, True]).reset_index(drop=True)
