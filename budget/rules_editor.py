"""Rule management for the UI: pattern suggestions, previews and safe edits of rules.yaml.

rules.yaml is edited as text (not re-dumped through PyYAML) so that hand-written
comments and ordering survive. Every edit is validated with parse_rules before
it is written; a failed validation leaves the file untouched.
"""

import re
from pathlib import Path

import pandas as pd
import yaml

from budget.categorizer import AMOUNT_SIGNS, GROUPS, TEXT_FIELDS, Rule, parse_rules
from budget.fileio import write_text_atomic
from budget.privacy import PLACEHOLDER

UI_MARKER = "  # --- added from UI (newest first) ---"
CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_SUGGESTED_WORDS = 3
REGEX_SPECIAL = set(".^$*+?{}[]\\|()")


def _escape(text: str) -> str:
    """Escape regex metacharacters only (re.escape also escapes spaces and '&', which reads badly)."""
    return "".join("\\" + ch if ch in REGEX_SPECIAL else ch for ch in text)


def suggest_pattern(counterparty: str) -> str:
    """Suggest a regex for a counterparty, dropping store numbers and payment codes.

    'Lidl dakuje 164' -> 'lidl dakuje', 'BOLT.EUO2609181350' -> 'bolt\\.euo',
    '8003 TERNO Ovsistsk' -> 'terno ovsistsk'.
    """
    words: list[str] = []
    for token in counterparty.lower().lstrip("*").split():
        if not any(ch.isdigit() for ch in token):
            words.append(token)
        elif token.isdigit() or len(re.split(r"\d", token, maxsplit=1)[0]) < 3:
            # pure number or short code like 'sk0403': skip leading ones, stop after words
            if words:
                break
            continue
        else:
            words.append(re.split(r"\d", token, maxsplit=1)[0])
            break
        if len(words) == MAX_SUGGESTED_WORDS:
            break
    words = [w for w in words if w not in {"-", "*"}]
    if not words:
        return _escape(counterparty.strip().lower())
    return _escape(" ".join(words))


def clean_match(match: dict[str, str | None]) -> dict[str, str]:
    """Keep non-empty patterns of known fields, in canonical order."""
    unknown = set(match) - set(TEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown match field(s): {', '.join(sorted(unknown))}")
    return {f: p for f in TEXT_FIELDS if (p := match.get(f)) is not None and p.strip() != ""}


def build_rule(match: dict[str, str | None], sign: str | None = None, category: str = "_preview") -> Rule:
    """Compile a single candidate rule, rejecting ones that would match anonymized rows."""
    patterns = clean_match(match)
    if not patterns:
        raise ValueError("at least one pattern is required")
    if sign is not None and sign not in AMOUNT_SIGNS:
        raise ValueError(f"sign must be one of {', '.join(AMOUNT_SIGNS)}")
    spec: dict = dict(patterns)
    if sign:
        spec["amount"] = sign
    rule = parse_rules({"groups": {category: "variable"}, "rules": [{"category": category, "match": spec}]}).rules[0]
    if any(p.search(PLACEHOLDER) for p in rule.patterns.values()):
        raise ValueError(f"pattern would match anonymized '{PLACEHOLDER}' transactions")
    return rule


def preview_matches(df: pd.DataFrame, match: dict[str, str | None], sign: str | None = None) -> pd.DataFrame:
    """Rows the candidate rule matches, regardless of rule order."""
    rule = build_rule(match, sign)
    mask = [rule.matches(row) for _, row in df.iterrows()]
    return df[mask]


def _yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _find_top_level_key(lines: list[str], key: str) -> int:
    for i, line in enumerate(lines):
        if re.fullmatch(rf"{key}:\s*(#.*)?", line.rstrip("\n")):
            return i
    raise ValueError(f"rules file: top-level '{key}:' block not found (flow style like '{key}: {{}}' is not supported)")


def _format_rule(category: str, match: dict[str, str], sign: str | None, indent: str = "  ") -> list[str]:
    parts = [f"{field}: {_yaml_quote(pattern)}" for field, pattern in match.items()]
    if sign:
        parts.append(f"amount: {sign}")
    return [f"{indent}- category: {category}\n", f"{indent}  match: {{{', '.join(parts)}}}\n"]


def _rule_spans(lines: list[str]) -> list[tuple[int, int]]:
    """Line ranges [start, end) of each rule item under `rules:`, without trailing comments or blank lines."""
    first = _find_top_level_key(lines, "rules")
    starts: list[int] = []
    end = len(lines)
    indent: int | None = None
    for i in range(first + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = len(lines[i]) - len(lines[i].lstrip(" "))
        if current == 0:
            end = i
            break
        if stripped == "-" or stripped.startswith("- "):
            indent = current if indent is None else indent
            if current == indent:
                starts.append(i)
    spans = []
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else end
        while stop > start + 1 and (not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")):
            stop -= 1
        spans.append((start, stop))
    return spans


def _load(path: Path) -> tuple[list[str], dict, int]:
    """Lines of the file (newline terminated), its groups and its rule count."""
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines, data.get("groups") or {}, len(data.get("rules") or [])


def _checked_spans(lines: list[str], rule_count: int, index: int | None = None) -> list[tuple[int, int]]:
    spans = _rule_spans(lines)
    if len(spans) != rule_count:
        raise ValueError("rules file layout is not supported for editing here (edit rules.yaml by hand)")
    if index is not None and not 0 <= index < rule_count:
        raise ValueError(f"rule index {index} is out of range")
    return spans


def _apply_category(lines: list[str], groups: dict, category: str, new_group: str | None) -> None:
    """Make sure `category` exists, adding it to `groups:` when new_group is given."""
    if not CATEGORY_RE.match(category):
        raise ValueError("category must be lowercase letters, digits and underscores, starting with a letter")
    if new_group is not None:
        if new_group not in GROUPS:
            raise ValueError(f"group must be one of {', '.join(GROUPS)}")
        if category in groups and groups[category] != new_group:
            raise ValueError(f"category '{category}' already exists in group '{groups[category]}'")
        if category not in groups:
            lines.insert(_find_top_level_key(lines, "groups") + 1, f"  {category}: {new_group}\n")
    elif category not in groups:
        raise ValueError(f"unknown category '{category}' (choose a group to create it)")


def _write(path: Path, lines: list[str], expected_rules: int) -> None:
    """Validate the new text and replace the file atomically; on error the file is untouched."""
    new_text = "".join(lines)
    data = yaml.safe_load(new_text) or {}
    parse_rules(data)  # raises ValueError
    if len(data.get("rules") or []) != expected_rules:
        raise ValueError("internal error: edit changed the number of rules unexpectedly")
    write_text_atomic(path, new_text)


def add_rule(
    path: str | Path,
    category: str,
    match: dict[str, str | None],
    sign: str | None = None,
    new_group: str | None = None,
) -> None:
    """Insert a rule at the top of `rules:` (so it wins) and optionally a new category into `groups:`."""
    path = Path(path)
    patterns = clean_match(match)
    build_rule(patterns, sign, category if CATEGORY_RE.match(category) else "_preview")
    lines, groups, count = _load(path)
    _apply_category(lines, groups, category, new_group)

    rule_lines = _format_rule(category, patterns, sign)
    idx = _find_top_level_key(lines, "rules")
    if idx + 1 < len(lines) and lines[idx + 1].rstrip("\n") == UI_MARKER:
        lines[idx + 2 : idx + 2] = rule_lines
    else:
        lines[idx + 1 : idx + 1] = [UI_MARKER + "\n", *rule_lines, "\n"]
    _write(path, lines, count + 1)


def update_rule(
    path: str | Path,
    index: int,
    category: str,
    match: dict[str, str | None],
    sign: str | None = None,
    new_group: str | None = None,
) -> None:
    """Replace the rule at `index` in place. Comments inside that rule's own lines are not kept."""
    path = Path(path)
    patterns = clean_match(match)
    build_rule(patterns, sign, category if CATEGORY_RE.match(category) else "_preview")
    lines, groups, count = _load(path)
    start, stop = _checked_spans(lines, count, index)[index]
    indent = " " * (len(lines[start]) - len(lines[start].lstrip(" ")))
    lines[start:stop] = _format_rule(category, patterns, sign, indent)
    _apply_category(lines, groups, category, new_group)
    _write(path, lines, count)


def delete_rule(path: str | Path, index: int) -> None:
    """Remove the rule at `index`. Its category stays in `groups:`."""
    path = Path(path)
    lines, _, count = _load(path)
    start, stop = _checked_spans(lines, count, index)[index]
    del lines[start:stop]
    _write(path, lines, count - 1)


def move_rule(path: str | Path, index: int, direction: str) -> None:
    """Swap the rule with its neighbour; comments and blank lines between rules stay in place."""
    path = Path(path)
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    other = index - 1 if direction == "up" else index + 1
    lines, _, count = _load(path)
    spans = _checked_spans(lines, count, index)
    if not 0 <= other < count:
        raise ValueError("rule is already at the " + ("top" if direction == "up" else "bottom"))
    (a_start, a_stop), (b_start, b_stop) = sorted([spans[index], spans[other]])
    first, second = lines[a_start:a_stop], lines[b_start:b_stop]
    lines[a_start:b_stop] = second + lines[a_stop:b_start] + first
    _write(path, lines, count)
