from pathlib import Path

import pytest

from budget.categorizer import categorize, load_rules
from budget.parsers.csob import parse_csob
from budget.rules_editor import UI_MARKER, add_rule, delete_rule, move_rule, preview_matches, suggest_pattern, update_rule

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"
ROOT = Path(__file__).parent.parent
RULES = """# hand-written header comment
groups:
  groceries: variable  # food
  rent: fixed

rules:
  - category: rent
    match: {message: najom}
"""


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


@pytest.mark.parametrize(
    ("counterparty", "expected"),
    [
        ("Lidl dakuje 164", "lidl dakuje"),
        ("BOLT.EUO2609181350", r"bolt\.euo"),
        ("8003 TERNO Ovsistsk", "terno ovsistsk"),
        ("SK0403 H&M BA EUROVEA", "h&m ba eurovea"),
        ("Dr.Max 324 BA Avion", r"dr\.max"),
        ("NYX*CoffeeUsro", r"nyx\*coffeeusro"),
        ("12345", "12345"),
    ],
)
def test_suggest_pattern(counterparty, expected):
    assert suggest_pattern(counterparty) == expected


def test_add_rule_keeps_comments_and_puts_rule_first(rules_path):
    add_rule(rules_path, "groceries", {"counterparty": "shop one"})
    text = rules_path.read_text()
    assert "# hand-written header comment" in text
    assert "groceries: variable  # food" in text
    ruleset = load_rules(rules_path)
    assert [r.category for r in ruleset.rules] == ["groceries", "rent"]
    assert text.count(UI_MARKER) == 1


def test_newest_ui_rule_comes_first(rules_path):
    add_rule(rules_path, "groceries", {"counterparty": "first"})
    add_rule(rules_path, "rent", {"counterparty": "second"})
    text = rules_path.read_text()
    assert text.count(UI_MARKER) == 1
    assert [r.patterns["counterparty"].pattern for r in load_rules(rules_path).rules[:2]] == ["second", "first"]


def test_add_rule_with_new_category_and_sign(rules_path):
    add_rule(rules_path, "sport", {"counterparty": "gym"}, sign="negative", new_group="variable")
    ruleset = load_rules(rules_path)
    assert ruleset.groups["sport"] == "variable"
    assert ruleset.rules[0].sign == "negative"


def test_pattern_with_quotes_round_trips(rules_path):
    add_rule(rules_path, "groceries", {"counterparty": "mcdonald's|a: b"})
    assert load_rules(rules_path).rules[0].patterns["counterparty"].pattern == "mcdonald's|a: b"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"category": "groceries", "match": {"counterparty": "("}}, "invalid regex"),
        ({"category": "nope", "match": {"counterparty": "x"}}, "unknown category"),
        ({"category": "Bad Name", "match": {"counterparty": "x"}, "new_group": "fixed"}, "lowercase"),
        ({"category": "rent", "match": {"counterparty": "x"}, "new_group": "variable"}, "already exists"),
        ({"category": "groceries", "match": {"counterparty": "priv"}}, "anonymized"),
        ({"category": "groceries", "match": {"counterparty": "."}}, "anonymized"),
        ({"category": "groceries", "match": {"counterparty": "  "}}, "at least one pattern"),
        ({"category": "groceries", "match": {"iban": "x"}}, "unknown match field"),
    ],
)
def test_invalid_rule_leaves_file_untouched(rules_path, kwargs, error):
    with pytest.raises(ValueError, match=error):
        add_rule(rules_path, **kwargs)
    assert rules_path.read_text() == RULES


def test_preview_matches_what_categorize_does_after_saving(rules_path):
    df = parse_csob(FIXTURE)
    preview = preview_matches(df, {"counterparty": "shop|gym"}, "negative")
    add_rule(rules_path, "groceries", {"counterparty": "shop|gym"}, sign="negative")
    after = categorize(df, load_rules(rules_path))
    assert len(preview) == 2
    assert (after["category"] == "groceries").sum() == len(preview)


RULES_MANY = """# header
groups:
  groceries: variable
  rent: fixed
  sport: variable

rules:
  # --- fixed ---
  - category: rent
    match: {message: najom}

  # --- variable ---
  - category: groceries
    match: {counterparty: 'lidl|tesco'}
  - category: sport
    match:
      counterparty: gym
      amount: negative

# trailing comment
"""


@pytest.fixture
def many_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(RULES_MANY)
    return path


def categories(path: Path) -> list[str]:
    return [r.category for r in load_rules(path).rules]


def test_update_rule_replaces_in_place_and_keeps_comments(many_path):
    update_rule(many_path, 1, "sport", {"counterparty": "lidl", "message": "x"}, sign="negative")
    ruleset = load_rules(many_path)
    assert categories(many_path) == ["rent", "sport", "sport"]
    assert set(ruleset.rules[1].patterns) == {"counterparty", "message"}
    assert ruleset.rules[1].sign == "negative"
    text = many_path.read_text()
    for kept in ("# header", "# --- fixed ---", "# --- variable ---", "# trailing comment"):
        assert kept in text


def test_update_rule_can_create_category(many_path):
    update_rule(many_path, 0, "housing", {"message": "najom"}, new_group="fixed")
    assert load_rules(many_path).groups["housing"] == "fixed"
    assert categories(many_path)[0] == "housing"


def test_update_multiline_rule(many_path):
    update_rule(many_path, 2, "groceries", {"counterparty": "gym"})
    assert categories(many_path) == ["rent", "groceries", "groceries"]
    assert load_rules(many_path).rules[2].sign is None


def test_delete_rule(many_path):
    delete_rule(many_path, 1)
    assert categories(many_path) == ["rent", "sport"]
    text = many_path.read_text()
    assert "# --- variable ---" in text and "lidl" not in text
    assert load_rules(many_path).groups["groceries"] == "variable"


def test_move_rule_swaps_neighbours_and_keeps_comments_in_place(many_path):
    move_rule(many_path, 1, "up")
    assert categories(many_path) == ["groceries", "rent", "sport"]
    lines = many_path.read_text().splitlines()
    assert lines.index("  # --- fixed ---") < lines.index("  # --- variable ---")
    move_rule(many_path, 0, "down")
    assert categories(many_path) == ["rent", "groceries", "sport"]


def test_move_multiline_rule(many_path):
    move_rule(many_path, 2, "up")
    assert categories(many_path) == ["rent", "sport", "groceries"]
    assert load_rules(many_path).rules[1].sign == "negative"


@pytest.mark.parametrize(
    ("action", "error"),
    [
        (lambda p: move_rule(p, 0, "up"), "already at the top"),
        (lambda p: move_rule(p, 2, "down"), "already at the bottom"),
        (lambda p: delete_rule(p, 3), "out of range"),
        (lambda p: update_rule(p, -1, "rent", {"message": "x"}), "out of range"),
        (lambda p: move_rule(p, 0, "left"), "direction"),
    ],
)
def test_invalid_edits_leave_file_untouched(many_path, action, error):
    with pytest.raises(ValueError, match=error):
        action(many_path)
    assert many_path.read_text() == RULES_MANY


def test_shipped_rules_file_survives_edit_roundtrip(tmp_path):
    """The demo rules must be editable by the UI functions."""
    shipped = tmp_path / "rules.yaml"
    shipped.write_text((ROOT / "examples/demo/rules.yaml").read_text())
    before = categories(shipped)
    if len(before) < 3:
        pytest.skip("rules.yaml has fewer than 3 rules")
    move_rule(shipped, 1, "down")
    move_rule(shipped, 2, "up")
    assert categories(shipped) == before
    update_rule(shipped, 0, before[0], {"counterparty": "x|y"})
    assert categories(shipped) == before
    delete_rule(shipped, len(before) - 1)
    assert len(categories(shipped)) == len(before) - 1


def test_edit_keeps_file_permissions(many_path):
    many_path.chmod(0o644)
    delete_rule(many_path, 0)
    assert many_path.stat().st_mode & 0o777 == 0o644
