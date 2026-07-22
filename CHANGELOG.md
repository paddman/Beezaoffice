# Changelog

## 0.16.1 — Agent Rooms Release

Status: source implemented on `main`; room artwork is intentionally mocked with replaceable placeholders.

### Added

- Persistent personal Room for every registered Agent
- Tenant-scoped `agent_rooms` and `agent_room_notes` tables
- Alembic revision `20260722_0003`
- Agent Room directory with Department and Availability filters
- Interactive room scene using Background, Avatar and Foreground layers
- Work Desk showing tasks assigned to the Agent
- Direct Inbox using the existing Collaboration Message bus
- Meeting list using structured Meeting participation
- Notes and curated Memory board
- Unified Activity timeline
- Evaluation counters and Runtime dispatch visibility
- Direct room actions:
  - Message Agent
  - Assign work and optionally dispatch immediately
  - Add Note, Memory or Reminder
  - Customize Room status, theme and assets
- Generic office and Agent avatar placeholder SVG assets
- Exact per-Agent asset paths for later artwork replacement
- Governance permissions and Commercial feature enforcement
- Agent Room data added to Pilot restore and customer-acceptance checks

### Asset contract

```text
app/static/assets/agent-rooms/<agent-key>/background.webp
app/static/assets/agent-rooms/<agent-key>/avatar.webp
app/static/assets/agent-rooms/<agent-key>/foreground.webp
```

Recommended sizes:

```text
background.webp   1920×1080
avatar.webp       1024×1024 transparent
foreground.webp   1920×1080 transparent
```

### Changed

- Application runtime now starts through `agent_room_bootstrap:app`
- Application version moved to `0.16.1`
- Pilot and production Compose defaults moved to `0.16.1`
- Signed installer expects Alembic head `20260722_0003`
- Pilot integration gate verifies room creation, asset contract and restore persistence
- Customer acceptance journey includes the Agent Room directory and workspace

### Operational boundaries

- An Agent Room is a persistent control-plane workspace, not a separate Agent process.
- Direct messages are delivered to the Collaboration inbox; immediate Runtime response depends on the Agent integration.
- Custom images are not included yet and must be placed at the documented Static paths or configured through Room customization.
- Room Notes are curated operational context, not an unrestricted autonomous long-term memory system.

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
