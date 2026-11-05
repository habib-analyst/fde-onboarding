"""Onboarding service: state machine, resume, and TTFV analytics.

State machine per tenant step:
    locked -> available -> in_progress -> completed
                                        -> skipped   (optional steps only)

Percentile method (documented): nearest-rank. For percentile p over the
sorted values v[0..n-1], the result is v[ceil(p/100 * n) - 1]. Median is
p50 under the same method.
"""
from __future__ import annotations

import math
import uuid

from .clock import ClockFn, system_clock
from .flow import FLOW, STEPS_BY_ID, VALUE_STEP_ID
from .store import Store


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class ValidationFailed(Exception):
    def __init__(self, message: str, progress: dict):
        super().__init__(message)
        self.progress = progress


def nearest_rank(values_sorted: list[float], p: float) -> float:
    if not values_sorted:
        raise ValueError("no values")
    rank = math.ceil(p / 100 * len(values_sorted))
    idx = min(max(rank - 1, 0), len(values_sorted) - 1)
    return values_sorted[idx]


class OnboardingService:
    def __init__(self, store: Store, clock: ClockFn | None = None):
        self.store = store
        self.clock = clock or system_clock

    # tenants -------------------------------------------------------
    def create_tenant(self, name: str, tenant_id: str | None = None) -> dict:
        tenant_id = tenant_id or f"t_{uuid.uuid4().hex[:12]}"
        if self.store.get_tenant(tenant_id):
            raise ConflictError(f"tenant {tenant_id} already exists")
        rows = []
        for i, step in enumerate(FLOW):
            state = "available" if not step.prerequisites else "locked"
            rows.append((step.id, state))
        tenant = self.store.create_tenant(tenant_id, name, self.clock(), rows)
        return tenant

    def _require_tenant(self, tenant_id: str) -> dict:
        t = self.store.get_tenant(tenant_id)
        if not t:
            raise NotFoundError(f"tenant {tenant_id} not found")
        return t

    # progress ------------------------------------------------------
    def get_progress(self, tenant_id: str) -> dict:
        tenant = self._require_tenant(tenant_id)
        raw = {r["step_id"]: r for r in self.store.list_steps(tenant_id)}
        steps = []
        for step in FLOW:
            r = raw[step.id]
            steps.append(
                {
                    **step.to_dict(),
                    "state": r["state"],
                    "started_at": r["started_at"],
                    "completed_at": r["completed_at"],
                    "error": r["error"],
                }
            )
        current = next(
            (s["id"] for s in steps if s["state"] in ("available", "in_progress")), None
        )
        ttfv = None
        value_row = raw[VALUE_STEP_ID]
        if value_row["state"] == "completed" and value_row["completed_at"] is not None:
            ttfv = value_row["completed_at"] - tenant["created_at"]
        return {
            "tenant_id": tenant["id"],
            "name": tenant["name"],
            "created_at": tenant["created_at"],
            "steps": steps,
            "current_step": current,
            "completed_count": sum(1 for s in steps if s["state"] == "completed"),
            "ttfv_seconds": ttfv,
        }

    def _refresh_availability(self, tenant_id: str) -> None:
        raw = {r["step_id"]: r for r in self.store.list_steps(tenant_id)}
        for step in FLOW:
            row = raw[step.id]
            if row["state"] != "locked":
                continue
            if all(raw[p]["state"] in ("completed", "skipped") for p in step.prerequisites):
                self.store.update_step(tenant_id, step.id, state="available")

    # submit / skip ---------------------------------------------------
    def submit_step(self, tenant_id: str, step_id: str, payload: dict) -> dict:
        self._require_tenant(tenant_id)
        step = STEPS_BY_ID.get(step_id)
        if not step:
            raise NotFoundError(f"step {step_id} not found")
        row = self.store.get_step(tenant_id, step_id)
        if row["state"] == "locked":
            raise ConflictError(
                f"step {step_id} is locked; prerequisites incomplete: {list(step.prerequisites)}"
            )
        if row["state"] in ("completed", "skipped"):
            raise ConflictError(f"step {step_id} is already {row['state']}")
        now = self.clock()
        started = row["started_at"] if row["started_at"] is not None else now
        ok, error = step.predicate(payload or {})
        if not ok:
            self.store.update_step(
                tenant_id, step_id, state="in_progress", started_at=started, error=error
            )
            raise ValidationFailed(error, self.get_progress(tenant_id))
        self.store.update_step(
            tenant_id,
            step_id,
            state="completed",
            started_at=started,
            completed_at=now,
            error=None,
        )
        self._refresh_availability(tenant_id)
        return self.get_progress(tenant_id)

    def skip_step(self, tenant_id: str, step_id: str) -> dict:
        self._require_tenant(tenant_id)
        step = STEPS_BY_ID.get(step_id)
        if not step:
            raise NotFoundError(f"step {step_id} not found")
        if not step.optional:
            raise ConflictError(f"step {step_id} is required and cannot be skipped")
        row = self.store.get_step(tenant_id, step_id)
        if row["state"] == "locked":
            raise ConflictError(f"step {step_id} is locked; prerequisites incomplete")
        if row["state"] in ("completed", "skipped"):
            raise ConflictError(f"step {step_id} is already {row['state']}")
        self.store.update_step(
            tenant_id, step_id, state="skipped", completed_at=self.clock(), error=None
        )
        self._refresh_availability(tenant_id)
        return self.get_progress(tenant_id)

    # analytics -------------------------------------------------------
    def compute_stats(self) -> dict:
        tenants = self.store.list_tenants()
        completion_counts = {s.id: 0 for s in FLOW}
        drop_off = {s.id: 0 for s in FLOW}
        ttfvs: list[float] = []
        per_tenant = {}
        for tenant in tenants:
            progress = self.get_progress(tenant["id"])
            per_tenant[tenant["id"]] = progress["ttfv_seconds"]
            if progress["ttfv_seconds"] is not None:
                ttfvs.append(progress["ttfv_seconds"])
            states = {s["id"]: s["state"] for s in progress["steps"]}
            for s in FLOW:
                if states[s.id] == "completed":
                    completion_counts[s.id] += 1
            if progress["ttfv_seconds"] is None:
                # Drop-off step = earliest step (in flow order) not completed/skipped.
                for s in FLOW:
                    if states[s.id] not in ("completed", "skipped"):
                        drop_off[s.id] += 1
                        break
        ttfvs.sort()
        stats = {
            "tenant_count": len(tenants),
            "value_step": VALUE_STEP_ID,
            "value_completed_count": len(ttfvs),
            "ttfv_seconds": ttfvs,
            "per_tenant_ttfv_seconds": per_tenant,
            "completion_counts": completion_counts,
            "drop_off": drop_off,
            "percentile_method": "nearest-rank",
            "ttfv_median_seconds": nearest_rank(ttfvs, 50) if ttfvs else None,
            "ttfv_p90_seconds": nearest_rank(ttfvs, 90) if ttfvs else None,
        }
        return stats
