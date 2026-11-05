# Launch Note — fde-onboarding

20-point pre-launch checklist. Every item PASS or N/A with a reason.

1. **Tests green** — PASS: 11/11 pytest tests pass (`python3 -m pytest tests/ -q`).
2. **README accurate** — PASS: flow, state machine, analytics method, and measured numbers match the code and the seeded cohort output.
3. **No secrets in the repo** — PASS: no credentials anywhere; fixture values are obviously synthetic (`fixture`, `simulate_failure`, example.com domains).
4. **No payment / billing code** — PASS: no payments, no card handling, $0 to run.
5. **No network calls** — PASS: the API and the fixture test-connection are fully in-process; tests use FastAPI TestClient.
6. **Deterministic results** — PASS: injected FakeClock drives all fixture timestamps; pinned TTFV/drop-off numbers are asserted in tests.
7. **Error handling** — PASS: locked-step and required-skip conflicts return 409, validation failures return 400 with the error recorded on the step, unknown tenants return 404.
8. **Tenant isolation** — PASS: header-scoped tenant routes return 404 on mismatch; covered by a dedicated cross-tenant test.
9. **Resumability verified** — PASS: reopen-resume test compares full progress before/after reopening the SQLite file and finishes the journey on the reopened store.
10. **Input validation** — PASS: every step has a completion predicate over its payload; invalid payloads never complete a step.
11. **State machine integrity** — PASS: prerequisites gate availability; completed/skipped steps cannot be resubmitted.
12. **Analytics method documented** — PASS: nearest-rank percentile method stated in code, README, and the stats response itself.
13. **Scope honesty** — PASS: README states plainly that the test connection is a simulated fixture and tenant scoping uses a fixture header, not real auth.
14. **Dependencies minimal and free** — PASS: fastapi, pydantic, pytest, httpx only; all open source.
15. **No personal data** — PASS: all tenants, emails, and domains are invented fixtures.
16. **No AI/automation disclosure issues** — PASS: public copy describes the software only; no internal process language.
17. **License/attribution** — N/A: no third-party code or assets copied in; standard library plus the frameworks in item 14.
18. **Demo path works** — PASS: `python3 -m fde_onboarding.demo` seeds the cohort and prints the pinned stats.
19. **File hygiene** — PASS: no caches, databases, or build artifacts in the project tree beyond source, tests, and docs.
20. **Rollback** — N/A: local project with no deployed service, no production data, and no external side effects to roll back.
