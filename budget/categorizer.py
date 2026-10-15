"""Rule-based categorization: the first matching rule wins.

rules.yaml format:
    groups:            # category -> group (income | fixed | variable | transfer)
      groceries: variable
    rules:
      - category: groceries
        match:
          counterparty: "lidl|tesco"   # regex, case-insensitive, re.search
          amount: negative             # optional: positive | negative
All conditions inside one rule's `match` must hold (AND).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

GROUPS = ("income", "fixed", "variable", "transfer")
TEXT_FIELDS = ("counterparty", "message", "raw_category")
AMOUNT_SIGNS = ("positive", "negative")


@dataclass(frozen=True)
class Rule:
    category: str
    patterns: dict[str, re.Pattern]
    sign: str | None = None

    def matches(self, row: pd.Series) -> bool:
        if self.sign == "positive" and not row["amount"] > 0:
            return False
        if self.sign == "negative" and not row["amount"] < 0:
            return False
        return all(pattern.search(row[field] or "") for field, pattern in self.patterns.items())


@dataclass(frozen=True)
class RuleSet:
    groups: dict[str, str]
    rules: list[Rule]


def parse_rules(data: dict) -> RuleSet:
    """Validate a rules mapping (as loaded from YAML) and compile its regexes."""
    groups = data.get("groups") or {}
    for category, group in groups.items():
        if group not in GROUPS:
            raise ValueError(f"category '{category}': unknown group '{group}' (expected one of {', '.join(GROUPS)})")

    rules = []
    for i, entry in enumerate(data.get("rules") or [], start=1):
        category = entry.get("category")
        if category not in groups:
            raise ValueError(f"rule {i}: category '{category}' is not defined in groups")
        match = dict(entry.get("match") or {})
        sign = match.pop("amount", None)
        if sign is not None and sign not in AMOUNT_SIGNS:
            raise ValueError(f"rule {i}: amount must be one of {', '.join(AMOUNT_SIGNS)}")
        unknown = set(match) - set(TEXT_FIELDS)
        if unknown:
            raise ValueError(f"rule {i}: unknown match field(s): {', '.join(sorted(unknown))}")
        if not match and sign is None:
            raise ValueError(f"rule {i}: empty match")
        patterns = {}
        for field, pattern in match.items():
            try:
                patterns[field] = re.compile(str(pattern), re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"rule {i}: invalid regex for {field}: {exc}") from None
        rules.append(Rule(category=category, patterns=patterns, sign=sign))
    return RuleSet(groups=dict(groups), rules=rules)


def load_rules(path: str | Path) -> RuleSet:
    with open(path, encoding="utf-8") as f:
        return parse_rules(yaml.safe_load(f) or {})


def categorize(df: pd.DataFrame, ruleset: RuleSet) -> pd.DataFrame:
    """Return a copy of df with `category`, `group` and `rule_index` columns.

    rule_index is the 0-based position of the winning rule in ruleset.rules; all three
    columns are None when no rule matches.
    """

    def first_match(row: pd.Series) -> int | None:
        return next((i for i, rule in enumerate(ruleset.rules) if rule.matches(row)), None)

    out = df.copy()
    indexes = [first_match(row) for _, row in out.iterrows()]
    categories = [ruleset.rules[i].category if i is not None else None for i in indexes]
    groups = [ruleset.groups[c] if c else None for c in categories]
    out["category"] = pd.Series(categories, index=out.index, dtype=object)
    out["group"] = pd.Series(groups, index=out.index, dtype=object)
    out["rule_index"] = pd.Series(indexes, index=out.index, dtype=object)
    return out
