"""Seeded cohort: scripted journeys driven by a FakeClock so every
duration is exact.

Cohort (8 tenants, signup base = FakeClock start):
- alpha   completes all steps                       TTFV  3600s (1h)
- beta    completes, skips optional SSO             TTFV  7200s (2h)
- charlie completes all steps                       TTFV 10800s (3h)
- dana    completes all steps                       TTFV 14400s (4h)
- erin    completes all steps                       TTFV 36000s (10h)
- frank   stalls at connect_data_source (failed test connection)
- grace   abandons after workspace_setup
- heidi   stalls at import_data

Pinned stats over this cohort:
- TTFV values sorted: [3600, 7200, 10800, 14400, 36000]
- median (nearest-rank p50) = 10800, p90 (nearest-rank) = 36000
- completion_counts: workspace 8, invite 7, connect 6, sso 5, import 5, value 5
  (SSO completed by alpha, charlie, dana, erin and heidi; beta skips it)
- drop_off: invite_team 1 (grace), connect_data_source 1 (frank), import_data 1 (heidi)
"""
from __future__ import annotations

from .clock import FakeClock
from .service import OnboardingService, ValidationFailed

HOUR = 3600.0

_PAYLOADS = {
    "workspace_setup": lambda name: {"workspace_name": f"{name} HQ"},
    "invite_team": lambda name: {"invites": [f"teammate@{name}.example.com"]},
    "connect_data_source": lambda name: {
        "connector": "postgres",
        "test_connection": True,
        "connection_params": {},
    },
    "configure_sso": lambda name: {"provider": "okta", "domain": f"{name}.example.com"},
    "import_data": lambda name: {"dataset_name": "customers", "row_count": 1200},
    "first_dashboard_view": lambda name: {"event": "dashboard_viewed"},
}


def _do(svc: OnboardingService, tid: str, step: str, name: str) -> None:
    svc.submit_step(tid, step, _PAYLOADS[step](name))


def _complete_journey(svc: OnboardingService, clock: FakeClock, tid: str, name: str, ttfv: float, skip_sso: bool = False) -> None:
    """Complete the whole flow; the value step lands exactly ttfv after signup."""
    base = clock()
    steps = ["workspace_setup", "invite_team", "connect_data_source"]
    # Spread the early steps over the first half of the TTFV window.
    for i, step in enumerate(steps):
        clock.set(base + ttfv * (i + 1) / 10)
        _do(svc, tid, step, name)
    clock.set(base + ttfv * 0.5)
    if skip_sso:
        svc.skip_step(tid, "configure_sso")
    else:
        _do(svc, tid, "configure_sso", name)
    clock.set(base + ttfv * 0.75)
    _do(svc, tid, "import_data", name)
    clock.set(base + ttfv)
    _do(svc, tid, "first_dashboard_view", name)


def seed_cohort(svc: OnboardingService, clock: FakeClock) -> list[str]:
    base = clock()
    created: list[str] = []

    def new_tenant(tid: str, name: str) -> str:
        clock.set(base)
        svc.create_tenant(name=name, tenant_id=tid)
        created.append(tid)
        return tid

    _complete_journey(svc, clock, new_tenant("t_alpha", "alpha"), "alpha", 1 * HOUR)
    _complete_journey(svc, clock, new_tenant("t_beta", "beta"), "beta", 2 * HOUR, skip_sso=True)
    _complete_journey(svc, clock, new_tenant("t_charlie", "charlie"), "charlie", 3 * HOUR)
    _complete_journey(svc, clock, new_tenant("t_dana", "dana"), "dana", 4 * HOUR)
    _complete_journey(svc, clock, new_tenant("t_erin", "erin"), "erin", 10 * HOUR)

    # frank: stalls at connect_data_source — test connection fails.
    tid = new_tenant("t_frank", "frank")
    clock.set(base + 600)
    _do(svc, tid, "workspace_setup", "frank")
    clock.set(base + 1200)
    _do(svc, tid, "invite_team", "frank")
    clock.set(base + 1800)
    try:
        svc.submit_step(
            tid,
            "connect_data_source",
            {
                "connector": "postgres",
                "test_connection": True,
                "connection_params": {"simulate_failure": True},
            },
        )
    except ValidationFailed:
        pass

    # grace: abandons after workspace_setup.
    tid = new_tenant("t_grace", "grace")
    clock.set(base + 300)
    _do(svc, tid, "workspace_setup", "grace")

    # heidi: completes through SSO, stalls at import_data (never submits it).
    tid = new_tenant("t_heidi", "heidi")
    for i, step in enumerate(["workspace_setup", "invite_team", "connect_data_source", "configure_sso"]):
        clock.set(base + 600 * (i + 1))
        _do(svc, tid, step, "heidi")

    clock.set(base)
    return created
