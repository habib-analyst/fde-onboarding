"""Demo: seed the fixture cohort into a SQLite file and print TTFV stats.

Usage: python3 -m fde_onboarding.demo [db_path]
"""
from __future__ import annotations

import json
import sys

from .clock import FakeClock
from .fixtures import seed_cohort
from .service import OnboardingService
from .store import Store


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "demo_onboarding.db"
    clock = FakeClock()
    svc = OnboardingService(Store(db_path), clock=clock)
    ids = seed_cohort(svc, clock)
    print(f"seeded tenants: {ids}")
    print(json.dumps(svc.compute_stats(), indent=2))


if __name__ == "__main__":
    main()
