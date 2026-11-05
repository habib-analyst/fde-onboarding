"""Flow definition: ordered steps, guidance, prerequisites, predicates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

FIXTURE_CONNECTORS = {"salesforce", "hubspot", "postgres", "google_sheets"}
SSO_PROVIDERS = {"okta", "azure_ad", "google_workspace"}
VALUE_STEP_ID = "first_dashboard_view"


def simulate_test_connection(connector: str, params: dict[str, Any] | None) -> tuple[bool, str]:
    """In-process fixture test-connection. Deterministic failure modes:
    - unknown connector name
    - payload sets simulate_failure=true
    - payload endpoint == 'unreachable'
    """
    params = params or {}
    if connector not in FIXTURE_CONNECTORS:
        return False, f"unknown fixture connector: {connector!r}"
    if params.get("simulate_failure"):
        return False, "fixture test connection failed (simulate_failure)"
    if params.get("endpoint") == "unreachable":
        return False, "fixture test connection failed: endpoint unreachable"
    return True, "fixture test connection succeeded"


# Each predicate returns (ok, error_or_None)
Predicate = Callable[[dict[str, Any]], "tuple[bool, str | None]"]


def _workspace(payload):
    name = payload.get("workspace_name")
    if not isinstance(name, str) or not name.strip():
        return False, "workspace_name is required and must be non-empty"
    return True, None


def _invite(payload):
    invites = payload.get("invites")
    if not isinstance(invites, list) or not invites:
        return False, "invites must be a non-empty list of email addresses"
    for e in invites:
        if not isinstance(e, str) or "@" not in e or "." not in e.split("@")[-1]:
            return False, f"invalid invite email: {e!r}"
    return True, None


def _connect(payload):
    connector = payload.get("connector")
    if not isinstance(connector, str) or not connector:
        return False, "connector is required"
    if not payload.get("test_connection"):
        return False, "test_connection must be attempted (set test_connection=true)"
    ok, msg = simulate_test_connection(connector, payload.get("connection_params") or {})
    if not ok:
        return False, msg
    return True, None


def _sso(payload):
    provider = payload.get("provider")
    if provider not in SSO_PROVIDERS:
        return False, f"provider must be one of {sorted(SSO_PROVIDERS)}"
    domain = payload.get("domain")
    if not isinstance(domain, str) or "." not in domain:
        return False, "domain is required and must look like a domain"
    return True, None


def _import(payload):
    dataset = payload.get("dataset_name")
    if not isinstance(dataset, str) or not dataset.strip():
        return False, "dataset_name is required"
    rows = payload.get("row_count")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
        return False, "row_count must be a positive integer"
    return True, None


def _value(payload):
    if payload.get("event") != "dashboard_viewed" and payload.get("viewed") is not True:
        return False, "payload must record the first dashboard view (event='dashboard_viewed')"
    return True, None


@dataclass(frozen=True)
class StepDef:
    id: str
    title: str
    guidance: str
    prerequisites: tuple[str, ...] = ()
    optional: bool = False
    predicate: Predicate | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "guidance": self.guidance,
            "prerequisites": list(self.prerequisites),
            "optional": self.optional,
            "is_value_step": self.id == VALUE_STEP_ID,
        }


FLOW: tuple[StepDef, ...] = (
    StepDef(
        id="workspace_setup",
        title="Create your workspace",
        guidance="Pick a workspace name. This creates the tenant workspace every later step configures. Takes about a minute.",
        prerequisites=(),
        optional=False,
        predicate=_workspace,
    ),
    StepDef(
        id="invite_team",
        title="Invite your team",
        guidance="Invite at least one teammate by email. Invited members get the viewer role until an admin promotes them.",
        prerequisites=("workspace_setup",),
        optional=False,
        predicate=_invite,
    ),
    StepDef(
        id="connect_data_source",
        title="Connect a data source",
        guidance="Choose a fixture connector (salesforce, hubspot, postgres, google_sheets) and run the test connection. A failed test keeps this step open so you can fix the settings and retry.",
        prerequisites=("invite_team",),
        optional=False,
        predicate=_connect,
    ),
    StepDef(
        id="configure_sso",
        title="Configure SSO (optional)",
        guidance="Optionally connect Okta, Azure AD, or Google Workspace for single sign-on. You can skip this and set it up later from Settings.",
        prerequisites=("connect_data_source",),
        optional=True,
        predicate=_sso,
    ),
    StepDef(
        id="import_data",
        title="Import your data",
        guidance="Import a first dataset from the connected source. Name the dataset and confirm the row count is above zero.",
        prerequisites=("connect_data_source", "configure_sso"),
        optional=False,
        predicate=_import,
    ),
    StepDef(
        id="first_dashboard_view",
        title="See your first dashboard",
        guidance="Open the dashboard built from your imported data. Reaching this step is the first-value event used for time-to-first-value analytics.",
        prerequisites=("import_data",),
        optional=False,
        predicate=_value,
    ),
)

STEPS_BY_ID = {s.id: s for s in FLOW}
