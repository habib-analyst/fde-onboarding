# fde-onboarding

Self-serve customer onboarding for a multi-tenant SaaS, built as a step
state machine with per-tenant progress, guided checklists, resumability,
and time-to-first-value (TTFV) analytics.

A new tenant walks a six-step flow — create workspace, invite team,
connect a data source, configure SSO, import data, see the first
dashboard — and the engine tracks exactly where every tenant is, what
they are stuck on, and how long first value took.

## The flow

| Step | Required | Completes when |
|---|---|---|
| `workspace_setup` | yes | a non-empty workspace name is submitted |
| `invite_team` | yes | at least one valid invite email is submitted |
| `connect_data_source` | yes | a fixture connector is chosen and the test connection succeeds |
| `configure_sso` | optional (skippable) | a supported SSO provider and domain are submitted |
| `import_data` | yes | a dataset name and a positive row count are submitted |
| `first_dashboard_view` | yes — **the value step** | the first dashboard view event is recorded |

Each step carries short in-app guidance text, served by the API alongside
the step list, and declares its prerequisites. `import_data`, for
example, requires both `connect_data_source` and `configure_sso`
(completed or skipped).

## State machine

Every step of every tenant is in one state:

```
locked -> available -> in_progress -> completed
                                   -> skipped   (optional steps only)
```

- A step is `locked` until all its prerequisites are completed or skipped.
- Submitting to a locked step is rejected with **409** — no out-of-order
  completion.
- Skipping a required step is rejected with **409**; skipping an optional
  step unlocks its dependents.
- A submission that fails validation (including a failed fixture test
  connection) returns **400**, keeps the step `in_progress`, and records
  the error on the step, so the tenant sees what to fix and can retry.
  A retry with corrected settings completes the step and clears the error.
- Tenant scoping: tenant routes require an `X-Tenant-Id` header matching
  the tenant in the path. A mismatch returns **404**, so one tenant
  cannot read or write another tenant's progress.

## Resumability

All state lives in SQLite. `GET /tenants/{id}/progress` returns the
tenant's exact current step states, timestamps, and recorded errors.
Closing the process and reopening the same database file resumes every
tenant exactly where they left off — this is covered by a test that
reopens the store mid-journey and compares progress before and after.

## TTFV analytics

The value step is `first_dashboard_view`. A tenant's TTFV is the time
from tenant creation to completion of that step, using an injected clock
so fixture journeys have exact, reproducible durations.

`GET /stats` returns:

- per-tenant TTFV and the sorted cohort TTFV list,
- median and p90 TTFV,
- per-step completion counts,
- per-step drop-off counts, where a tenant who has not reached first
  value counts against the earliest step they have not completed or
  skipped.

**Percentile method: nearest-rank.** For percentile *p* over sorted
values `v[0..n-1]`, the result is `v[ceil(p/100 * n) - 1]`. The median is
p50 under the same method.

### Measured results on the seeded fixture cohort

The seeded cohort has 8 tenants: 5 complete the flow, 1 stalls at the
data-source step on a failed test connection, 1 stalls at data import,
and 1 abandons after workspace creation.

- TTFV values: **3,600 / 7,200 / 10,800 / 14,400 / 36,000 seconds**
- Median TTFV: **10,800s (3h)** · p90 TTFV: **36,000s (10h)**
- Completion counts: workspace 8, invite 7, connect 6, SSO 5, import 5, value 5
- Drop-off: invite 1, connect 1, import 1, all other steps 0
- Test suite: **11 tests, all passing** (`python3 -m pytest tests/ -q`)

## API

| Method | Route | Notes |
|---|---|---|
| `POST` | `/tenants` | create a tenant (optional client-supplied id) |
| `GET` | `/flow/steps` | step definitions with guidance text |
| `GET` | `/tenants/{id}/steps` | step states for the tenant (header-scoped) |
| `GET` | `/tenants/{id}/progress` | full resumable progress (header-scoped) |
| `POST` | `/tenants/{id}/steps/{step}/submit` | submit a step payload |
| `POST` | `/tenants/{id}/steps/{step}/skip` | skip an optional step |
| `GET` | `/tenants/{id}/stats` | per-tenant TTFV summary |
| `GET` | `/stats` | cohort TTFV, completion, and drop-off stats |

## Run it

```bash
pip install fastapi pydantic pytest httpx
python3 -m pytest tests/ -q          # 11 tests
python3 -m fde_onboarding.demo       # seed the fixture cohort, print stats
uvicorn fde_onboarding.app:app       # serve the API locally
```

## Scope honesty

This is a local, deterministic demo. The data-source "test connection"
is a fixture simulated in-process: it succeeds for the named fixture
connectors (`salesforce`, `hubspot`, `postgres`, `google_sheets`) and
has deterministic failure modes (unknown connector, an explicitly
simulated failure, an unreachable endpoint) so stuck-and-retry journeys
can be exercised. No real connectors, no network calls, no external
services. Tenant scoping uses a fixture header rather than real auth.
