import pytest
from fastapi.testclient import TestClient

from fde_onboarding.app import create_app
from fde_onboarding.clock import FakeClock
from fde_onboarding.fixtures import seed_cohort
from fde_onboarding.service import OnboardingService
from fde_onboarding.store import Store

BASE = 1_704_067_200.0


@pytest.fixture()
def env(tmp_path):
    clock = FakeClock(BASE)
    app = create_app(tmp_path / "test.db", clock=clock)
    return TestClient(app), clock, app


def hdr(tid):
    return {"X-Tenant-Id": tid}


def create(client, tid="t1", name="acme"):
    r = client.post("/tenants", json={"name": name, "tenant_id": tid})
    assert r.status_code == 201, r.text
    return r.json()


def submit(client, tid, step, payload):
    return client.post(
        f"/tenants/{tid}/steps/{step}/submit", json={"payload": payload}, headers=hdr(tid)
    )


def do_step(client, tid, step, payload):
    r = submit(client, tid, step, payload)
    assert r.status_code == 200, r.text
    return r.json()


WS = {"workspace_name": "Acme HQ"}
INV = {"invites": ["teammate@acme.example.com"]}
CONN = {"connector": "postgres", "test_connection": True, "connection_params": {}}
SSO = {"provider": "okta", "domain": "acme.example.com"}
IMP = {"dataset_name": "customers", "row_count": 500}
VAL = {"event": "dashboard_viewed"}


def walk_to_connect(client, tid="t1"):
    create(client, tid)
    do_step(client, tid, "workspace_setup", WS)
    do_step(client, tid, "invite_team", INV)


# ---------------------------------------------------------------- tests

def test_happy_path_full_journey(env):
    client, clock, _ = env
    create(client)
    clock.advance(600)
    p = do_step(client, "t1", "workspace_setup", WS)
    assert p["current_step"] == "invite_team"
    do_step(client, "t1", "invite_team", INV)
    do_step(client, "t1", "connect_data_source", CONN)
    do_step(client, "t1", "configure_sso", SSO)
    do_step(client, "t1", "import_data", IMP)
    clock.advance(3000)
    p = do_step(client, "t1", "first_dashboard_view", VAL)
    states = {s["id"]: s["state"] for s in p["steps"]}
    assert all(v == "completed" for v in states.values())
    assert p["completed_count"] == 6
    assert p["current_step"] is None
    assert p["ttfv_seconds"] == 3600.0


def test_steps_list_with_guidance(env):
    client, _, _ = env
    r = client.get("/flow/steps")
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert [s["id"] for s in steps] == [
        "workspace_setup", "invite_team", "connect_data_source",
        "configure_sso", "import_data", "first_dashboard_view",
    ]
    assert all(s["guidance"] for s in steps)
    assert steps[3]["optional"] is True
    assert steps[5]["is_value_step"] is True


def test_prerequisite_enforcement(env):
    client, _, _ = env
    create(client)
    # invite_team is locked until workspace_setup completes
    r = submit(client, "t1", "invite_team", INV)
    assert r.status_code == 409
    # import_data is locked even later in the flow too
    r = submit(client, "t1", "import_data", IMP)
    assert r.status_code == 409


def test_optional_skip_and_required_skip_rejection(env):
    client, _, _ = env
    walk_to_connect(client)
    do_step(client, "t1", "connect_data_source", CONN)
    # required step cannot be skipped
    r = client.post("/tenants/t1/steps/import_data/skip", headers=hdr("t1"))
    assert r.status_code == 409
    r = client.post("/tenants/t1/steps/workspace_setup/skip", headers=hdr("t1"))
    assert r.status_code == 409
    # optional SSO can be skipped, and skipping unlocks import_data
    r = client.post("/tenants/t1/steps/configure_sso/skip", headers=hdr("t1"))
    assert r.status_code == 200
    states = {s["id"]: s["state"] for s in r.json()["steps"]}
    assert states["configure_sso"] == "skipped"
    assert states["import_data"] == "available"
    p = do_step(client, "t1", "import_data", IMP)
    assert p["current_step"] == "first_dashboard_view"


def test_failed_test_connection_keeps_step_open_and_retry_succeeds(env):
    client, _, _ = env
    walk_to_connect(client)
    bad = {
        "connector": "postgres",
        "test_connection": True,
        "connection_params": {"simulate_failure": True},
    }
    r = submit(client, "t1", "connect_data_source", bad)
    assert r.status_code == 400
    step = [s for s in r.json()["progress"]["steps"] if s["id"] == "connect_data_source"][0]
    assert step["state"] == "in_progress"
    assert "simulate_failure" in step["error"]
    # unknown connector also fails and keeps the step open
    r = submit(client, "t1", "connect_data_source",
               {"connector": "not-a-connector", "test_connection": True, "connection_params": {}})
    assert r.status_code == 400
    # retry with a good fixture connection succeeds
    p = do_step(client, "t1", "connect_data_source", CONN)
    step = [s for s in p["steps"] if s["id"] == "connect_data_source"][0]
    assert step["state"] == "completed"
    assert step["error"] is None


def test_payload_validation_keeps_step_in_progress(env):
    client, _, _ = env
    create(client)
    r = submit(client, "t1", "workspace_setup", {"workspace_name": "  "})
    assert r.status_code == 400
    step = r.json()["progress"]["steps"][0]
    assert step["state"] == "in_progress"
    assert step["error"]


def test_reopen_resume_equivalence(tmp_path):
    db = tmp_path / "resume.db"
    clock = FakeClock(BASE)
    svc = OnboardingService(Store(db), clock=clock)
    svc.create_tenant(name="acme", tenant_id="t1")
    svc.submit_step("t1", "workspace_setup", WS)
    svc.submit_step("t1", "invite_team", INV)
    before = svc.get_progress("t1")
    svc.store.close()
    # Fresh process/store on the same SQLite file resumes identically.
    svc2 = OnboardingService(Store(db), clock=clock)
    after = svc2.get_progress("t1")
    assert before == after
    assert after["current_step"] == "connect_data_source"
    # And the resumed tenant can finish the flow.
    svc2.submit_step("t1", "connect_data_source", CONN)
    assert svc2.get_progress("t1")["current_step"] == "configure_sso"


def test_cohort_dropoff_counts_pinned(tmp_path):
    clock = FakeClock(BASE)
    svc = OnboardingService(Store(tmp_path / "c.db"), clock=clock)
    seed_cohort(svc, clock)
    stats = svc.compute_stats()
    assert stats["tenant_count"] == 8
    assert stats["completion_counts"] == {
        "workspace_setup": 8,
        "invite_team": 7,
        "connect_data_source": 6,
        "configure_sso": 5,
        "import_data": 5,
        "first_dashboard_view": 5,
    }
    assert stats["drop_off"] == {
        "workspace_setup": 0,
        "invite_team": 1,
        "connect_data_source": 1,
        "configure_sso": 0,
        "import_data": 1,
        "first_dashboard_view": 0,
    }


def test_cohort_ttfv_median_p90_pinned(tmp_path):
    clock = FakeClock(BASE)
    svc = OnboardingService(Store(tmp_path / "c.db"), clock=clock)
    seed_cohort(svc, clock)
    stats = svc.compute_stats()
    assert stats["ttfv_seconds"] == [3600.0, 7200.0, 10800.0, 14400.0, 36000.0]
    assert stats["ttfv_median_seconds"] == 10800.0
    assert stats["ttfv_p90_seconds"] == 36000.0
    assert stats["percentile_method"] == "nearest-rank"
    assert stats["value_completed_count"] == 5
    assert stats["per_tenant_ttfv_seconds"]["t_beta"] == 7200.0
    assert stats["per_tenant_ttfv_seconds"]["t_frank"] is None


def test_stats_endpoint_matches_service(env):
    client, clock, app = env
    seed_cohort(app.state.service, clock)
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["ttfv_median_seconds"] == 10800.0
    assert body["ttfv_p90_seconds"] == 36000.0


def test_cross_tenant_isolation(env):
    client, _, _ = env
    create(client, "t1", "acme")
    create(client, "t2", "globex")
    # Reading another tenant's progress with the wrong header -> 404
    r = client.get("/tenants/t1/progress", headers=hdr("t2"))
    assert r.status_code == 404
    # No header at all -> 404
    r = client.get("/tenants/t1/progress")
    assert r.status_code == 404
    # Submitting into another tenant's flow -> 404
    r = client.post(
        "/tenants/t1/steps/workspace_setup/submit",
        json={"payload": WS}, headers=hdr("t2"),
    )
    assert r.status_code == 404
    # Own header works
    r = client.get("/tenants/t1/progress", headers=hdr("t1"))
    assert r.status_code == 200
    # Unknown tenant -> 404 even with a matching header
    r = client.get("/tenants/nope/progress", headers=hdr("nope"))
    assert r.status_code == 404
