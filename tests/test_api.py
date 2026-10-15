import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from budget.api import create_app
from budget.privacy import PLACEHOLDER

FIXTURE = Path(__file__).parent / "fixtures" / "csob_sample.csv"
RULES = """groups:
  sport: variable
  rent: fixed
  salary: income
rules:
  - category: rent
    match: {message: najom}
  - category: salary
    match: {raw_category: prijata, amount: positive}
"""


@pytest.fixture
def paths(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(FIXTURE, data / "export.csv")
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    private = tmp_path / "private.yaml"
    private.write_text("patterns:\n  - 'test gym'\n")
    budgets = tmp_path / "budgets.yaml"
    return {"data": data, "rules": rules, "private": private, "budgets": budgets}


@pytest.fixture
def client(paths) -> TestClient:
    app = create_app(paths["data"], paths["rules"], paths["private"], budgets_path=paths["budgets"])
    return TestClient(app, base_url="http://127.0.0.1")


def test_meta(client):
    body = client.get("/api/meta").json()
    assert body["count"] == 6
    assert body["date_from"] == "2026-09-01"
    # fixture ends on 28.9., so September is not fully covered
    assert body["months"] == [
        {"month": "2026-09", "count": 6, "partial": True, "income": 2500.0, "expenses": pytest.approx(-728.30)}
    ]
    assert {"name": "rent", "group": "fixed"} in body["categories"]


def test_summary(client):
    body = client.get("/api/summary", params={"month": "2026-09"}).json()
    assert body["income"] == 2500.0
    assert body["fixed"] == -650.0
    assert body["variable"] == pytest.approx(-78.30)
    assert body["balance"] == pytest.approx(1771.70)
    assert body["uncategorized_count"] == 4
    assert body["uncategorized_income"] == 0.0
    assert body["uncategorized_expenses"] == pytest.approx(-78.30)
    assert {"category": "rent", "group": "fixed", "amount": -650.0} in body["by_category"]


def test_trend(client):
    body = client.get("/api/trend").json()
    assert body["months"][0]["month"] == "2026-09"
    assert body["months"][0]["balance"] == pytest.approx(1771.70)
    assert {"month": "2026-09", "category": "salary", "group": "income", "amount": 2500.0} in body["categories"]


def test_transactions_filters(client):
    assert client.get("/api/transactions").json()["count"] == 6
    unc = client.get("/api/transactions", params={"uncategorized": True}).json()
    assert unc["count"] == 4
    assert unc["total"] == pytest.approx(-78.30)
    found = client.get("/api/transactions", params={"q": "branch"}).json()
    assert [i["counterparty"] for i in found["items"]] == ["Shop One, Branch 2"]
    assert found["items"][0]["suggested_pattern"] == "shop one, branch"
    assert client.get("/api/transactions", params={"group": "fixed"}).json()["count"] == 1


def test_private_name_never_leaves_the_server(client):
    responses = [
        client.get("/api/transactions").text,
        client.get("/api/summary", params={"month": "2026-09"}).text,
        client.post("/api/rules/preview", json={"counterparty": "branch"}).text,
    ]
    assert all("TEST GYM" not in r for r in responses)
    items = client.get("/api/transactions").json()["items"]
    private = [i for i in items if i["is_private"]]
    assert len(private) == 1
    assert private[0]["counterparty"] == PLACEHOLDER
    assert private[0]["suggested_pattern"] is None


def test_preview_then_create_rule(client, paths):
    preview = client.post("/api/rules/preview", json={"counterparty": "shop|friend"}).json()
    assert preview["count"] == 2
    assert preview["changed"] == 0  # no category chosen yet

    resp = client.post(
        "/api/rules",
        json={"counterparty": "shop|friend", "category": "misc", "new_group": "variable"},
    )
    assert resp.status_code == 200
    assert "misc" in paths["rules"].read_text()
    summary = client.get("/api/summary", params={"month": "2026-09"}).json()
    assert summary["uncategorized_count"] == 2


def test_invalid_rule_is_400(client, paths):
    resp = client.post("/api/rules", json={"counterparty": "(", "category": "rent"})
    assert resp.status_code == 400
    assert "invalid regex" in resp.json()["detail"]
    assert paths["rules"].read_text() == RULES


def test_foreign_host_is_rejected(paths):
    app = create_app(paths["data"], paths["rules"], paths["private"], budgets_path=paths["budgets"])
    resp = TestClient(app, base_url="http://evil.example").get("/api/meta")
    assert resp.status_code == 400


def test_reload_picks_up_new_export(client, paths):
    (paths["data"] / "second.csv").write_text(
        FIXTURE.read_text().replace("28.9.2026,-11.00", "3.10.2026,-11.00")
    )
    assert client.post("/api/reload").json()["count"] == 7


def test_serves_built_frontend(paths, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ui</html>")
    client = TestClient(create_app(paths["data"], paths["rules"], paths["private"], dist, budgets_path=paths["budgets"]), base_url="http://127.0.0.1")
    assert "ui" in client.get("/").text
    assert client.get("/api/nope").status_code == 404


def post(client, path, **body):
    return client.post(path, json=body)


def test_rules_list_counts_wins_and_matches(client):
    rules = client.get("/api/rules").json()["rules"]
    assert [r["category"] for r in rules] == ["rent", "salary"]
    assert rules[0]["match"] == {"message": "najom"}
    assert rules[0]["wins"] == 1 and rules[0]["matches"] == 1
    assert rules[1]["sign"] == "positive" and rules[1]["group"] == "income"


def test_transactions_expose_winning_rule(client):
    items = client.get("/api/transactions", params={"group": "fixed"}).json()["items"]
    assert items[0]["rule_index"] == 0
    unc = client.get("/api/transactions", params={"uncategorized": True}).json()["items"]
    assert all(i["rule_index"] is None for i in unc)


def test_preview_shows_category_moves_for_a_new_rule(client):
    body = post(client, "/api/rules/preview", message="najom", category="sport", new_group="variable").json()
    assert body["changed"] == 1
    assert body["moves"] == [{"from": "rent", "to": "sport", "count": 1}]
    assert body["sample"][0]["category"] == "rent"
    assert body["sample"][0]["new_category"] == "sport"


def test_preview_of_an_edit_uses_replace_index(client):
    body = post(client, "/api/rules/preview", message="zzz", category="rent", replace_index=0).json()
    assert body["count"] == 0
    assert body["moves"] == [{"from": "rent", "to": None, "count": 1}]
    assert post(client, "/api/rules/preview", message="x", category="rent", replace_index=9).status_code == 400


def test_update_move_and_delete_rule(client, paths):
    assert client.put("/api/rules/0", json={"message": "najom", "category": "salary"}).status_code == 200
    summary = client.get("/api/summary", params={"month": "2026-09"}).json()
    assert summary["fixed"] == 0.0
    assert summary["income"] == 1850.0  # 2500 salary - 650 rent now categorized as salary

    assert client.post("/api/rules/1/move", json={"direction": "up"}).status_code == 200
    assert [r["category"] for r in client.get("/api/rules").json()["rules"]] == ["salary", "salary"]
    assert client.post("/api/rules/0/move", json={"direction": "up"}).status_code == 400

    assert client.delete("/api/rules/0").status_code == 200
    assert len(client.get("/api/rules").json()["rules"]) == 1
    assert client.delete("/api/rules/5").status_code == 400
    assert "salary" in paths["rules"].read_text()


def test_budgets_default_to_empty_and_can_be_saved(client, paths):
    body = client.get("/api/budgets", params={"month": "2026-09"}).json()
    assert body["items"] == [] and body["config"] == {"total": None, "groups": {}, "categories": {}}

    config = {"total": 1000, "groups": {"fixed": 700}, "categories": {"rent": 600, "sport": 5}}
    assert client.put("/api/budgets", json=config).status_code == 200
    assert paths["budgets"].exists()

    body = client.get("/api/budgets", params={"month": "2026-09"}).json()
    assert body["config"]["categories"] == {"rent": 600.0, "sport": 5.0}
    items = {(i["kind"], i["key"]): i for i in body["items"]}
    assert items[("total", None)]["spent"] == pytest.approx(728.30)
    assert items[("group", "fixed")]["status"] == "ok"  # 650 of 700, fixed budgets only turn "over"
    assert items[("category", "rent")]["spent"] == 650.0
    assert items[("category", "rent")]["status"] == "over"
    assert items[("category", "sport")]["spent"] == 0.0  # the gym payment is private and uncategorized
    assert all(i["known"] for i in body["items"])


def test_invalid_budgets_are_rejected(client, paths):
    assert client.put("/api/budgets", json={"total": -1}).status_code == 400
    assert client.put("/api/budgets", json={"groups": {"income": 100}}).status_code == 400
    assert not paths["budgets"].exists()


def test_plan_endpoint_and_budgets_keep_each_others_settings(client, paths):
    empty = client.get("/api/plan", params={"month": "2026-09"}).json()
    assert empty["balance"] is None and empty["month"]["available"] is None
    assert empty["savings"][0]["target"] is None

    plan = {"income": 2500, "savings": 1000, "min_balance": 1000, "balance": 3228.3, "balance_date": "2026-09-28"}
    assert client.put("/api/plan", json=plan).status_code == 200
    assert client.put("/api/budgets", json={"categories": {"rent": 700}}).status_code == 200  # must not erase the plan

    body = client.get("/api/plan", params={"month": "2026-09"}).json()
    assert body["plan"]["balance"] == 3228.3
    assert body["month"]["available"] == 1500.0
    assert body["month"]["allocated"] == 700.0
    assert body["month"]["spent"] == pytest.approx(728.30)
    # rent (650 of 700) is inside its budget; the other 78.30 is outside every budget
    assert body["month"]["outside_budgets"] == pytest.approx(78.30)
    assert body["month"]["free_remaining"] == pytest.approx(1500 - 700 - 78.30)
    assert body["month"]["budget_reserved"] == pytest.approx(50.0)  # 700 budgeted for rent, 650 of it used
    assert body["savings"][0]["saved"] == pytest.approx(1771.70)
    assert body["savings"][0]["met"] is True
    assert body["balance"]["current"] == 3228.3
    assert client.get("/api/budgets", params={"month": "2026-09"}).json()["config"]["categories"] == {"rent": 700.0}

    assert client.put("/api/plan", json={"income": 1}).status_code == 200  # replaces the plan, keeps budgets
    assert client.get("/api/plan", params={"month": "2026-09"}).json()["plan"]["balance"] is None
    assert client.get("/api/budgets", params={"month": "2026-09"}).json()["config"]["categories"] == {"rent": 700.0}


def test_invalid_plan_is_rejected(client, paths):
    assert client.put("/api/plan", json={"balance": 5}).status_code == 400
    assert client.put("/api/plan", json={"income": -1}).status_code == 400
    assert not paths["budgets"].exists()


def test_plan_endpoint_pace_forecast_and_typical(client, paths):
    plan = {"income": 2500, "savings": 1000, "min_balance": 1000, "balance": 3228.3, "balance_date": "2026-09-28"}
    assert client.put("/api/plan", json=plan).status_code == 200
    assert client.put("/api/budgets", json={"categories": {"rent": 700}}).status_code == 200

    body = client.get("/api/plan", params={"month": "2026-09"}).json()
    # the fixture ends on 28 September, so September is still in progress
    assert body["progress"]["as_of"] == "2026-09-28" and body["progress"]["days_left"] == 2
    assert body["progress"]["per_day"] == pytest.approx((1500 - 700 - 78.30) / 2, abs=0.01)  # free money / days left
    # fixed 650 paid + 50 of the rent budget unpaid + 78.30 variable * 30/28
    assert body["forecast"]["projected_spend"] == pytest.approx(650 + 50 + 78.30 * 30 / 28, abs=0.01)
    assert body["forecast"]["projected_balance"] is not None
    assert body["typical"] == {"months": [], "items": []}

    # a month the data has moved past is not in progress
    assert client.get("/api/plan", params={"month": "2026-08"}).json()["progress"] is None
    assert client.get("/api/plan", params={"month": "2026-08"}).json()["forecast"] is None


def test_plan_uses_the_income_that_actually_arrived(client, paths):
    # the fixture has 2500 of income in September; the expected income below must not matter for the plan
    plan = {"income": 1800, "savings": 1000}
    assert client.put("/api/plan", json=plan).status_code == 200
    month = client.get("/api/plan", params={"month": "2026-09"}).json()["month"]
    assert month["income"] == 2500.0
    assert month["available"] == 1500.0  # 2500 real income - 1000 savings, not 1800 - 1000
    assert month["expected_income"] == 1800.0
    assert month["income_pending"] is None  # the expectation is met

    # a plan without an expected income still works, the income comes from the data
    assert client.put("/api/plan", json={"savings": 1000}).status_code == 200
    assert client.get("/api/plan", params={"month": "2026-09"}).json()["month"]["available"] == 1500.0


def test_balance_goal_drives_the_plan_and_can_be_overridden(client, paths):
    # the fixture's movements in September add up to 1771.70, so the balance at the start of the month was 1456.60
    plan = {"savings": 1000, "min_balance": 1000, "balance": 3228.3, "balance_date": "2026-09-28", "start_month": "2026-09"}
    assert client.put("/api/plan", json=plan).status_code == 200

    month = client.get("/api/plan", params={"month": "2026-09"}).json()["month"]
    assert month["mode"] == "balance"
    assert month["opening_balance"] == 1456.6
    # the first planned month aims at the minimum balance plus the savings: 1000 + 1000
    assert month["goal"]["goal"] == 2000.0 and month["goal"]["source"] == "default"
    assert month["goal"]["from_opening"] == 2456.6  # the alternative: where the month started plus the savings
    assert month["available"] == 1956.6  # 1456.60 + 2500 income - 2000 goal
    assert month["remaining"] == pytest.approx(1956.6 - 728.30)  # what can still be spent

    assert client.put("/api/plan/goal", json={"month": "2026-09", "goal": 3000}).status_code == 200
    month = client.get("/api/plan", params={"month": "2026-09"}).json()["month"]
    assert month["goal"]["goal"] == 3000.0 and month["goal"]["source"] == "custom"
    assert month["goal"]["default"] == 2000.0
    assert month["available"] == pytest.approx(956.6)

    # saving the plan again does not lose the goals
    assert client.put("/api/plan", json=plan).status_code == 200
    assert client.get("/api/plan", params={"month": "2026-09"}).json()["plan"]["goals"] == {"2026-09": 3000.0}
    assert client.put("/api/plan/goal", json={"month": "2026-09", "goal": None}).status_code == 200
    assert client.get("/api/plan", params={"month": "2026-09"}).json()["plan"]["goals"] == {}
    assert client.put("/api/plan/goal", json={"month": "September", "goal": 5}).status_code == 400
    assert client.put("/api/plan/goal", json={"month": "2026-09", "goal": -5}).status_code == 400


def test_goal_mode_needs_a_start_month_and_ignores_earlier_months(client):
    plan = {"savings": 1000, "min_balance": 1000, "balance": 3228.3, "balance_date": "2026-09-28"}
    assert client.put("/api/plan", json=plan).status_code == 200
    assert client.get("/api/plan", params={"month": "2026-09"}).json()["month"]["mode"] == "income"  # no start month

    assert client.put("/api/plan", json={**plan, "start_month": "2026-10"}).status_code == 200
    body = client.get("/api/plan", params={"month": "2026-09"}).json()
    assert body["month"]["mode"] == "income"  # September is before the start
    assert body["savings"] == []  # earlier months are left out of the history, too
    assert body["plan"]["start_month"] == "2026-10"

    assert client.put("/api/plan", json={**plan, "start_month": "October"}).status_code == 400


def test_plan_without_balance_falls_back_to_income_minus_savings(client):
    assert client.put("/api/plan", json={"savings": 1000}).status_code == 200
    month = client.get("/api/plan", params={"month": "2026-09"}).json()["month"]
    assert month["mode"] == "income" and month["goal"] is None and month["available"] == 1500.0
