# Mama AI Final Backend Release Testing

This package adds a final, evidence-based release gate. It does not claim that
Mama AI can support millions of users. The included load test is a bounded
single-node validation intended to detect obvious regressions before release.
Large-scale capacity must be measured in a representative staging environment.

## Required gates

A production release is approved only when every required gate passes:

- at least 500 unit tests (the package currently discovers 532)
- at least 100 integration tests (the package currently discovers 123)
- at least 5 smoke tests
- Python compilation
- Bandit source scan
- dependency vulnerability scan
- repository secret scan
- Docker Compose validation and image build
- production environment validation
- live liveness/readiness smoke checks
- a verified database backup
- a clean Git working tree
- at least 100 load-test requests
- load-test error rate no greater than 1%
- load-test p95 no greater than 1000 ms

Thresholds can be tightened using `MAMA_RELEASE_*` environment variables. Do
not lower them to make a failing release pass.

## Local final validation

From the repository root:

```powershell
cd backend
python -m compileall -q app tests main.py
python -m unittest discover -s tests/unit -p "test_*.py"
python -m unittest discover -s tests/integration -p "test_*.py"
python -m unittest discover -s tests/smoke -p "test_*.py"
python -m app.release.bandit_gate
python -m pip_audit -r requirements-prod.txt
cd ..
docker compose -f compose.backend.yaml config --quiet
docker build --tag mama-ai-backend:release ./backend
python scripts/backend_smoke_test.py --base-url http://127.0.0.1:8000
python scripts/backend_load_test.py --url http://127.0.0.1:8000/health/ready --requests 100 --concurrency 10
```



### Bandit SQL review baseline

Bandit reports `B608` whenever a SQL string contains formatting, even when the
formatted parts are immutable table identifiers or fixed optional clauses.
Mama AI keeps a committed fingerprint allowlist at
`backend/release/bandit_b608_allowlist.json`. The review gate runs Bandit
normally and fails when any non-`B608` finding appears, when a SQL finding is
new or changed, or when an old review entry becomes stale. External SQL values
must continue to use SQLite parameter placeholders.

Do not add a fingerprint merely to make the gate pass. Review the exact query,
confirm that every identifier and clause is fixed by source code, and rerun all
database, authentication, multitenancy, and release tests.

Run Gitleaks separately against the complete Git history. Create and verify a
fresh database backup before setting those two evidence fields to `true`.

## Evidence and report

Copy `backend/release/evidence.example.json` to a local ignored filename such
as `backend/release/evidence.local.json`. Record only proven results. Never put
access tokens, passwords, API keys, email addresses, or filesystem secrets in
the evidence file.

Generate the report:

```powershell
python scripts/backend_release_gate.py --evidence backend/release/evidence.local.json --output backend/release/report.local.json
```

The command exits with status 1 when any required gate fails. The report
contains a SHA-256 digest of the canonical evidence. It does not sign the
report; release signing should be handled by the CI/CD or artefact registry.

## Lightweight load test

The load tester uses a fixed request count and bounded concurrency. It records
only aggregate status codes, exception class names, and latency percentiles.
Authorization headers and response bodies are not written to its result.

For a protected endpoint, supply the bearer token through the environment:

```powershell
$env:MAMA_RELEASE_BEARER_TOKEN = "your-local-token"
python scripts/backend_load_test.py --url http://127.0.0.1:8000/auth/me --requests 100 --concurrency 10
Remove-Item Env:MAMA_RELEASE_BEARER_TOKEN
```

## Failure recovery checks

Before release, exercise these runbooks in staging:

1. stop the worker during a claimed task and verify lease recovery;
2. restart the API with queued and approval-waiting tasks;
3. restore a verified backup into an isolated database path;
4. deploy the new immutable image and run smoke/load checks;
5. roll back to the previous immutable image and run the same checks;
6. confirm cross-user task, memory, audit, and session access remains blocked.

## CI release workflow

`.github/workflows/backend-release.yml` runs the final test, security, container,
and artefact gates on manual dispatch and release tags. A staging URL can be
provided through the `MAMA_RELEASE_STAGING_URL` repository variable. The
workflow does not fabricate backup or secret-scan evidence; those gates remain
explicit release responsibilities.
