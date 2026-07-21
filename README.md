# BeezaOffice

**AI Workforce Operating System** for operating 10–1,000 governed AI agents across private, enterprise and sovereign environments.

BeezaOffice is the command, governance, evidence and commercial control plane above OpenClaw, CherryAgent, Hermes Agent and thClaws. It turns Agent work into durable Missions, verified outcomes and measurable business value.

Current application version: **0.16.0 — Pilot Operations Release**.

## Platform roadmap

| Phase | Capability |
|---:|---|
| 2 | Runtime dispatch, synchronization, remote output, safe stop and approvals |
| 3 | Durable Runtime Event stream and Mission SSE |
| 4 | Typed Collaboration Bus, dependencies, mailbox, retry and escalation |
| 5 | Structured Agent meetings, bounded rounds and human decisions |
| 6 | Identity, RBAC, clearance, policy, budgets, approvals, kill switch and hash-chained audit |
| 7 | Agent Registry, Organization Graph, skills, capacity, reliability and delegation |
| 8 | Intelligent Agent/Runtime/Model routing, cost control, backpressure and failover |
| 9 | Evidence evaluation, acceptance checks, provenance, replay and quality scoring |
| 10 | Versioned SOP Builder, approval nodes, verification gates and rollback |
| 11 | A2A, MCP tools subset, OpenAI-compatible API, signed webhooks and Protocol Events |
| 12 | Multi-tenant Enterprise Platform, OIDC, scoped API keys, rate limits, backup/DR, SIEM and Kubernetes HA |
| 13 | Verified-work economics, Executive KPIs, Department scorecards, Agent economics, SLA, billing and Industry Packs |
| 14 | Tenant onboarding, signed licenses, contract entitlements, quota enforcement, deployment activation, white label, signed releases and production installer |

The numbered build roadmap ends at Phase 14. Version **0.16.0** adds the operational gate required to move that product into a real Pilot.

## 0.16.0 — Pilot Operations Release

A deployment cannot be promoted merely because the application starts. BeezaOffice records ten required gates:

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

### Pilot API

```text
GET  /api/pilot/checklist
GET  /api/pilot/status
GET  /api/pilot/programs
POST /api/pilot/programs
GET  /api/pilot/programs/{pilot_key}
POST /api/pilot/programs/{pilot_key}/gates
POST /api/pilot/programs/{pilot_key}/decision
```

Pilot evidence stores source, summary, metrics, artifact reference, actor, timestamps and an integrity hash. The UI includes a Pilot Operations Center showing gate completion and promotion state.

### Acceptance thresholds

Default Pilot criteria:

| Criterion | Default |
|---|---:|
| Runtime success rate | 99% |
| Maximum API error rate | 1% |
| Maximum p95 latency | 1,500 ms |
| Minimum security score | 90/100 |
| Backup/restore test | Required |
| Human customer sign-off | Required |

### Database migration

Current Alembic head:

```text
20260722_0002
```

`BEEZA_SCHEMA_STRICT=true` blocks readiness when the database revision does not match the application.

## Pilot automation

### 1. Automated integration gate

Workflow:

```text
.github/workflows/pilot-gate.yml
```

It automatically:

1. Builds the 0.16.0 image.
2. Generates ephemeral Ed25519 Pilot licenses for two Tenants.
3. Starts PostgreSQL, Redis and a deterministic four-Runtime simulator.
4. Applies Alembic migrations in strict mode.
5. Tests signed License enforcement and Tenant isolation.
6. Runs OpenClaw, CherryAgent, Hermes and thClaws adapter E2E contracts.
7. Runs the HTTP security review.
8. Runs a thresholded load test.
9. Destroys and restores PostgreSQL, then verifies persistent isolation.
10. Tests Alembic downgrade/upgrade without Pilot-data loss.

This workflow intentionally leaves `release_signed` and `customer_acceptance` pending. Simulated Runtime success is not presented as real customer validation.

### 2. Signed remote Pilot deployment

Workflow:

```text
.github/workflows/pilot-deploy.yml
```

Required GitHub Environment: `pilot-production`.

Required secrets:

```text
PILOT_SSH_PRIVATE_KEY
PILOT_ENV_B64
```

The environment file must contain a real signed License, production secrets, Runtime endpoints and:

```env
BEEZA_APP_VERSION=0.16.0
BEEZA_RELEASE_CHANNEL=pilot
BEEZA_LICENSE_MODE=enforce
BEEZA_SCHEMA_STRICT=true
BEEZA_FORCE_HTTPS=true
```

The workflow accepts a digest-pinned signed image, verifies the Cosign identity on the Pilot host, runs the migration-aware installer and verifies remote readiness.

### 3. Real Runtime and customer validation

Workflow:

```text
.github/workflows/pilot-promotion.yml
```

It runs against the deployed HTTPS Pilot environment and requires:

- Pilot URL and Tenant
- Pilot Program key
- Real Runtime keys
- Verified signed RC artifact reference
- Customer organization
- Human customer representative and acceptance note
- `PILOT_AUTH_TOKEN` GitHub Environment secret

The workflow then:

1. Records signed-release evidence.
2. Probes and dispatches a harmless E2E Mission to each configured real Runtime.
3. Runs a 50-concurrency, 60-second Pilot load gate.
4. Runs the production HTTP security review.
5. Requires all non-customer gates to pass.
6. Executes the first-customer acceptance journey.
7. Records human sign-off and accepts the Pilot.
8. Optionally creates and pushes stable tag `v0.16.0`.

The stable tag is therefore a promotion action after Pilot acceptance, not a substitute for Pilot acceptance.

## Architecture

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

## Commercial licensing

BeezaOffice accepts asymmetric JWT licenses bound to a Tenant and Deployment ID.

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

### Contract and License intersection

| Plan | Agents | Concurrent work | Tenants | Deployments |
|---|---:|---:|---:|---:|
| Team | 50 | 20 | 1 | 1 |
| Enterprise | 500 | 100 | 10 | 4 |
| Sovereign | 1,000 | 200 | 50 | 20 |

Effective features are the intersection of the active Contract and signed License. Effective quotas use the lower positive limit.

## Signed releases

`.github/workflows/release.yml` runs for `v*` tags and:

1. Builds and pushes the container to GHCR.
2. Generates SBOM and provenance attestations.
3. Signs the immutable image digest with Cosign and GitHub OIDC.
4. Verifies the signature.
5. Produces a Commercial Release Manifest and installer command.

Version 0.16.0 is seeded as `UNSIGNED`. It becomes a stable signed release only after a tag-triggered workflow successfully publishes its immutable artifact.

## Production installer

```text
deploy/install/install.sh
deploy/install/compose.production.yml
```

The installer requires:

- Docker Compose v2
- Digest-pinned image
- Cosign verification
- Signed License in `enforce` mode
- Alembic revision `20260722_0002`
- Pre-migration PostgreSQL backup

Example:

```bash
BEEZA_APP_VERSION=0.16.0 \
BEEZA_RELEASE_CHANNEL=pilot \
BEEZA_IMAGE=ghcr.io/paddman/beezaoffice:0.16.0@sha256:... \
BEEZA_COSIGN_IDENTITY=https://github.com/paddman/Beezaoffice/.github/workflows/release.yml@refs/tags/v0.16.0-rc.1 \
BEEZA_LICENSE_PUBLIC_KEY="$(awk '{printf "%s\\n",$0}' beeza-license-public.pem)" \
BEEZA_LICENSE_TOKEN="$(cat customer-a.jwt)" \
sh deploy/install/install.sh
```

The application binds to `127.0.0.1:8080` by default. External access requires an approved HTTPS reverse proxy or ingress.

## Local development

```bash
cp .env.example .env
docker compose -f compose.yml up -d --build --force-recreate
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f beezaoffice
```

The example environment uses `BEEZA_LICENSE_MODE=development` and does not represent a production Pilot.

## Core APIs

### Commercial

```text
GET  /api/commercial/status
GET  /api/commercial/onboarding
POST /api/commercial/onboarding
POST /api/commercial/onboarding/{key}/advance
GET  /api/commercial/license
POST /api/commercial/license/import
POST /api/commercial/license/verify
GET  /api/commercial/entitlements
GET  /api/commercial/brand
PUT  /api/commercial/brand
GET  /api/commercial/deployments
POST /api/commercial/deployments
POST /api/commercial/deployments/{key}/heartbeat
GET  /api/commercial/releases
POST /api/commercial/releases/publish
GET  /api/commercial/installer-config
```

### Business

```text
GET  /api/business/status
POST /api/business/sync
GET  /api/business/executive
GET  /api/business/departments
GET  /api/business/agents
GET  /api/business/outcomes
POST /api/business/outcomes
GET  /api/business/plans
GET  /api/business/billing
GET  /api/business/usage
POST /api/business/subscription
GET  /api/business/industry-packs
POST /api/business/industry-packs/{pack_key}/install
```

### Enterprise

```text
GET  /api/enterprise/status
GET  /api/enterprise/tenants
POST /api/enterprise/tenants
GET  /api/enterprise/identity-providers
POST /api/enterprise/identity-providers
POST /enterprise/sso/oidc/exchange
GET    /api/enterprise/api-keys
POST   /api/enterprise/api-keys
DELETE /api/enterprise/api-keys/{key_id}
GET  /api/enterprise/backup/plans
POST /api/enterprise/backup/plans/{plan_key}/runs
GET  /api/enterprise/siem/export
```

### Protocol

```text
GET  /.well-known/agent-card.json
POST /message:send
GET  /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}:cancel
GET  /tasks/{task_id}:subscribe
POST /mcp
POST /v1/chat/completions
POST /hooks/{channel}
```

## Health and observability

```text
GET /health/live
GET /health/ready
GET /api/health
GET /api/system/schema
GET /metrics     Authorization: Bearer $BEEZA_METRICS_TOKEN
```

## Security baseline

Version 0.16.0 adds:

- Configurable maximum request-body size
- HTTPS enforcement option
- CSP, frame denial, MIME sniffing protection and no-referrer policy
- API `no-store` caching policy
- HSTS when served through HTTPS
- Uvicorn Server-header suppression
- Signed License, Tenant and Governance enforcement

## Current release state

The source code, APIs, workflows and Pilot gates for **0.16.0** are on `main`.

Not automatically implied by source-code completion:

- A real Pilot host has been deployed
- A permanent Customer License has been issued
- Real OpenClaw/CherryAgent/Hermes/thClaws endpoints have passed E2E
- A customer representative has signed acceptance
- Stable tag `v0.16.0` has been pushed

Those states are recorded only after the corresponding workflows and evidence gates complete.

Detailed documentation:

- `docs/PHASE-12-ENTERPRISE-PLATFORM.md`
- `docs/PHASE-13-EXECUTIVE-BUSINESS.md`
- `docs/PHASE-14-COMMERCIAL-PRODUCTIZATION.md`
- `docs/RELEASE-0.16.0-PILOT-OPERATIONS.md`
