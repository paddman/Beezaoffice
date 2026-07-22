# BeezaOffice

**AI Workforce Operating System** for operating 10–1,000 governed AI agents across private, enterprise and sovereign environments.

BeezaOffice is the command, governance, evidence and commercial control plane above OpenClaw, CherryAgent, Hermes Agent and thClaws. It turns Agent work into durable Missions, verified outcomes and measurable business value.

Current application version: **0.16.1 — Agent Rooms Release**.

## What BeezaOffice provides

| Layer | Capability |
|---|---|
| Runtime | Dispatch, synchronization, output, safe stop and approvals |
| Collaboration | Typed messages, handoffs, dependencies, follow-up and escalation |
| Meetings | Structured roles, bounded rounds, decisions and action items |
| Governance | Identity, RBAC, clearance, policies, budgets, approvals, kill switch and audit |
| Registry | Organization Graph, skills, capacity, reliability and delegation |
| Scheduler | Explainable Agent/Runtime/Model routing, cost control and failover |
| Evaluation | Evidence, provenance, acceptance checks, replay and quality scoring |
| SOP | Versioned executable procedures, verification gates and rollback |
| Protocol | A2A, MCP subset, OpenAI-compatible API and signed webhooks |
| Enterprise | Multi-tenancy, OIDC, scoped API keys, rate limits, backup/DR and SIEM |
| Business | Executive KPIs, Agent economics, SLA, billing and Industry Packs |
| Commercial | Onboarding, signed licenses, entitlements, quotas, white label and signed releases |
| Pilot | Evidence-gated deployment, load, security, recovery and customer acceptance |
| Agent Rooms | Persistent personal workspace for every governed Agent |

The numbered build roadmap ends at Phase 14. Releases after that improve the product without inventing additional Phase numbers.

# 0.16.1 — Agent Rooms

Every registered Agent receives a persistent personal Room containing:

```text
Work Desk
Direct Inbox
Meetings
Notes & curated memory
Evaluation summary
Runtime activity
Replaceable room artwork
```

An Agent Room is a persistent control-plane workspace, not a separate Runtime process.

## Agent Room API

```text
GET    /api/agent-rooms/status
GET    /api/agent-rooms
GET    /api/agent-rooms/{agent_key}
PATCH  /api/agent-rooms/{agent_key}
POST   /api/agent-rooms/{agent_key}/messages
POST   /api/agent-rooms/{agent_key}/tasks
POST   /api/agent-rooms/{agent_key}/notes
DELETE /api/agent-rooms/{agent_key}/notes/{note_key}
```

## Agent Room actions

- **Message Agent** delivers a real Collaboration Message.
- **Assign Work** creates a fixed-Agent Collaboration Task and can dispatch immediately through the Agent's preferred Runtime.
- **Add Note** stores a Tenant-scoped Note, Memory or Reminder.
- **Customize** changes Room state, theme and visual asset paths.

Room work remains connected to the existing Mission, Runtime Event, Evaluation and Audit systems.

## Mock artwork and replacement paths

Version `0.16.1` includes generic placeholder artwork. Custom images can be added later without changing the Room system.

```text
app/static/assets/agent-rooms/<agent-key>/background.webp
app/static/assets/agent-rooms/<agent-key>/avatar.webp
app/static/assets/agent-rooms/<agent-key>/foreground.webp
```

Recommended dimensions:

| Layer | Size | Format |
|---|---:|---|
| Background | 1920×1080 | WebP |
| Avatar | 1024×1024 | Transparent WebP or PNG |
| Foreground | 1920×1080 | Transparent WebP or PNG |

Example:

```text
app/static/assets/agent-rooms/mira/background.webp
app/static/assets/agent-rooms/mira/avatar.webp
app/static/assets/agent-rooms/mira/foreground.webp
```

Then configure the Room with `/static/...` paths through **Customize Room**.

## Agent Room governance

```text
agent-room:read
agent-room:write
agent-room:message
agent-room:assign
```

Commercial boundaries:

- Room configuration and Notes require the `registry` feature.
- Direct messages and work assignment require the `collaboration` feature.
- Existing Tenant isolation, License enforcement, Governance and Kill Switch remain authoritative.

## Database migration

Current Alembic head:

```text
20260722_0003
```

New tables:

```text
agent_rooms
agent_room_notes
```

The migration downgrade is non-destructive because Room Notes may contain operational memory.

# Pilot Operations

BeezaOffice records ten release gates:

```text
release_signed
license_lifecycle
schema_migration
tenant_isolation
runtime_e2e
backup_restore
load_test
security_review
upgrade_rollback
customer_acceptance
```

Production promotion is blocked until every gate is `PASS` and an authorized Executive accepts the Pilot.

## Pilot API

```text
GET  /api/pilot/checklist
GET  /api/pilot/status
GET  /api/pilot/programs
POST /api/pilot/programs
GET  /api/pilot/programs/{pilot_key}
POST /api/pilot/programs/{pilot_key}/gates
POST /api/pilot/programs/{pilot_key}/decision
```

## Pilot workflows

### Automated integration gate

```text
.github/workflows/pilot-gate.yml
```

It builds `0.16.1`, applies Alembic `20260722_0003`, generates signed temporary Licenses for two Tenants, verifies Tenant isolation, creates Agent Rooms, tests four Runtime adapter contracts, runs load/security checks, destroys and restores PostgreSQL, and verifies the Agent Room migration rollback path.

Simulated Runtime success is not represented as real customer validation.

### Signed remote deployment

```text
.github/workflows/pilot-deploy.yml
```

Required GitHub Environment:

```text
pilot-production
```

Required deployment secrets:

```text
PILOT_SSH_PRIVATE_KEY
PILOT_SSH_KNOWN_HOSTS
PILOT_ENV_B64
```

The environment must contain:

```env
BEEZA_APP_VERSION=0.16.1
BEEZA_RELEASE_CHANNEL=pilot
BEEZA_LICENSE_MODE=enforce
BEEZA_SCHEMA_STRICT=true
BEEZA_FORCE_HTTPS=true
```

The workflow verifies the digest-pinned signed image, uses pinned SSH trust, runs the migration-aware installer and verifies remote version `0.16.1`.

### Real Runtime and customer validation

```text
.github/workflows/pilot-promotion.yml
```

Real promotion requires a deployed HTTPS Pilot, signed image digest, real Runtime endpoints, load/security evidence, named customer representative and human acceptance note.

The stable tag is a promotion action after accepted Pilot evidence, not a substitute for it.

# Architecture

```text
Enterprise Identity / Scoped API Key
        ↓ Tenant + rate limit
Commercial License ∩ Contract Entitlement
        ↓ Feature + quota enforcement
Governance and Audit
        ↓
Mission / Meeting / Collaboration / SOP / Protocol
        ↓
Agent Registry + Intelligent Scheduler
        ↓
Agent Rooms
        ↓
OpenClaw / CherryAgent / Hermes / thClaws
        ↓
Runtime Events + Evidence
        ↓
Evaluation + Approval + Replay
        ↓
Verified Business Outcome
        ↓
Pilot Evidence Gates
        ↓
Human Acceptance → Stable Release Promotion
```

# Commercial licensing

BeezaOffice accepts asymmetric JWT Licenses bound to a Tenant and Deployment ID.

```env
BEEZA_LICENSE_MODE=development
BEEZA_LICENSE_MODE=warn
BEEZA_LICENSE_MODE=enforce

BEEZA_DEPLOYMENT_ID=deployment:customer-primary
BEEZA_LICENSE_ISSUER=beezaoffice-license
BEEZA_LICENSE_AUDIENCE=beezaoffice
BEEZA_LICENSE_ALGORITHMS=EdDSA,RS256,ES256
BEEZA_LICENSE_PUBLIC_KEY=
BEEZA_LICENSE_TOKEN=
```

Production and Pilot environments use `enforce`. The raw License JWT is not persisted in the database.

Generate offline keys:

```bash
python deploy/license/generate-keys.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --public-key beeza-license-public.pem
```

Issue a License:

```bash
python deploy/license/issue-license.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --tenant-key tenant:customer-a \
  --deployment-id deployment:customer-a-primary \
  --plan-key plan:enterprise \
  --days 365 \
  --output customer-a.jwt
```

Verify offline:

```bash
python deploy/license/verify-license.py \
  --public-key beeza-license-public.pem \
  --token customer-a.jwt \
  --tenant-key tenant:customer-a \
  --deployment-id deployment:customer-a-primary
```

## Contract and License limits

| Plan | Agents | Concurrent work | Tenants | Deployments |
|---|---:|---:|---:|---:|
| Team | 50 | 20 | 1 | 1 |
| Enterprise | 500 | 100 | 10 | 4 |
| Sovereign | 1,000 | 200 | 50 | 20 |

Effective features are the intersection of the active Contract and signed License. Effective quotas use the lower positive limit.

# Signed releases

`.github/workflows/release.yml` runs for `v*` tags and:

1. Builds and pushes the container to GHCR.
2. Generates SBOM and provenance attestations.
3. Signs the immutable image digest with Cosign and GitHub OIDC.
4. Verifies the signature.
5. Produces a Commercial Release Manifest and installer command.

Version `0.16.1` is seeded as `UNSIGNED`. It becomes a signed release only after a tag-triggered workflow successfully publishes its immutable artifact.

# Production installer

```text
deploy/install/install.sh
deploy/install/compose.production.yml
```

The installer requires:

- Docker Compose v2
- Digest-pinned image
- Cosign verification
- Signed License in `enforce` mode
- Alembic revision `20260722_0003`
- Pre-migration PostgreSQL backup

Example:

```bash
BEEZA_APP_VERSION=0.16.1 \
BEEZA_RELEASE_CHANNEL=pilot \
BEEZA_IMAGE=ghcr.io/paddman/beezaoffice:0.16.1@sha256:... \
BEEZA_COSIGN_IDENTITY=https://github.com/paddman/Beezaoffice/.github/workflows/release.yml@refs/tags/v0.16.1-rc.1 \
BEEZA_LICENSE_PUBLIC_KEY="$(awk '{printf "%s\\n",$0}' beeza-license-public.pem)" \
BEEZA_LICENSE_TOKEN="$(cat customer-a.jwt)" \
sh deploy/install/install.sh
```

External access requires an approved HTTPS reverse proxy or ingress.

# Local development

```bash
cp .env.example .env
docker compose -f compose.yml up -d --build --force-recreate
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f beezaoffice
```

The example environment uses `BEEZA_LICENSE_MODE=development` and does not represent a production Pilot.

# Health and observability

```text
GET /health/live
GET /health/ready
GET /api/health
GET /api/system/schema
GET /metrics     Authorization: Bearer $BEEZA_METRICS_TOKEN
```

# Security baseline

- Protected `/api/*` endpoints require Bearer authentication.
- Configurable maximum request-body size.
- HTTPS enforcement option.
- CSP, frame denial, MIME sniffing protection and no-referrer policy.
- API `no-store` caching.
- HSTS when served through HTTPS.
- Uvicorn Server-header suppression.
- Signed License, Tenant and Governance enforcement.
- Agent Room asset paths restricted to `/static/`.

# Current release state

The source code, APIs, UI, migration, CI configuration and deploy defaults for **0.16.1** are on `main`.

Source completion does not automatically mean:

- A real Pilot host has been deployed.
- Permanent Customer Licenses have been issued.
- Real OpenClaw, CherryAgent, Hermes and thClaws endpoints have passed E2E.
- Customer room artwork has been supplied.
- A customer representative has accepted the release.
- Stable tag `v0.16.1` has been pushed.

Detailed documentation:

- `docs/RELEASE-0.16.1-AGENT-ROOMS.md`
- `docs/RELEASE-0.16.0-PILOT-OPERATIONS.md`
- `docs/RELEASE-0.16.0-EXECUTION-CHECKLIST.md`
- `docs/PHASE-12-ENTERPRISE-PLATFORM.md`
- `docs/PHASE-13-EXECUTIVE-BUSINESS.md`
- `docs/PHASE-14-COMMERCIAL-PRODUCTIZATION.md`
