# Changelog

## 0.16.0 — Pilot Operations Release

Status: source implemented on `main`; operational promotion requires real Pilot evidence.

### Added

- Pilot Program and Gate Evidence ledger
- Ten mandatory release gates:
  - Signed release
  - License lifecycle
  - Schema migration
  - Tenant isolation
  - Runtime E2E
  - Backup/restore
  - Load test
  - Security review
  - Upgrade/rollback
  - Customer acceptance
- Pilot Operations API and dashboard
- Alembic revision `20260722_0002`
- Enforce-mode signed Pilot License bundle generation
- Automated two-Tenant integration Pilot
- Deterministic OpenClaw, CherryAgent, Hermes and thClaws adapter simulator
- Real Runtime E2E validation runner
- Thresholded load-test runner
- HTTP security-review runner
- Real two-Licensed-Tenant isolation runner
- Destructive restore verification against an isolated PostgreSQL database
- First-customer acceptance journey with named human sign-off
- Signed remote Pilot deployment workflow
- Recovery/isolation workflow
- Cosign-verified promotion workflow
- Optional stable `v0.16.0` tag creation after Pilot acceptance

### Changed

- Application runtime now starts through `pilot_bootstrap:app`
- Centralized version and release channel in `app/release_version.py`
- Production installer performs pre-migration backup and Alembic upgrade
- Deployment registration reports application version and image digest
- Release-candidate tags publish candidate artifacts without stable aliases
- Pilot/candidate environments use a dedicated authenticated load-test capacity profile
- Stable channel restores the original Tenant request limit
- Dashboard API reads now use the operator Bearer token

### Security

- Protected `/api/*` endpoints require Bearer authentication
- Added configurable maximum request-body size
- Added optional HTTPS enforcement
- Added CSP, frame denial, MIME sniffing protection, no-referrer and Permissions Policy
- Added API `no-store` and HTTPS HSTS behavior
- Disabled Uvicorn Server response header
- Deployment workflow uses pinned SSH known-host data
- Promotion independently verifies the Cosign signature and deployed image digest

### Promotion requirements

The stable release is not considered complete until:

```text
10/10 Pilot gates PASS
Pilot accepted by an authorized Executive
Named customer representative recorded
Signed deployed image digest verified
Stable v0.16.0 tag pushed
Stable Release Manifest registered
```

### Not yet implied by this source release

- Real Pilot host deployment
- Permanent Customer License issuance
- Real Runtime success
- Customer acceptance
- Stable tag publication
- Production readiness
