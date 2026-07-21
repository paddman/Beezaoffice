# BeezaOffice

**AI Workforce Operating System** for operating 10–1,000 governed AI agents across private, sovereign and enterprise environments.

BeezaOffice is the command, governance and business-evidence plane above OpenClaw, CherryAgent, Hermes Agent and thClaws. It turns agent work into durable missions with collaboration, meetings, intelligent routing, evidence verification, reusable SOPs, standard protocols, enterprise controls and measurable business outcomes.

## Current platform

| Phase | Capability |
|---:|---|
| 2 | Runtime dispatch, synchronization, remote output, safe stop and approvals |
| 3 | Durable runtime-event stream and Mission SSE |
| 4 | Typed Collaboration Bus, dependencies, mailbox, retry and escalation |
| 5 | Structured agent meetings, bounded rounds and human decisions |
| 6 | Identity, RBAC, clearance, policy, budgets, approvals, kill switch and hash-chained audit |
| 7 | Agent Registry, organization graph, skills, capacity, reliability and delegation |
| 8 | Intelligent Agent/Runtime/Model routing, cost control, backpressure and failover |
| 9 | Evidence evaluation, acceptance checks, provenance, replay and quality scoring |
| 10 | Versioned SOP Builder, approval nodes, verification gates and rollback |
| 11 | A2A, MCP tools subset, OpenAI-compatible API, signed webhooks and protocol events |
| 12 | Multi-tenant Enterprise Platform, OIDC sessions, scoped API keys, rate limits, backup/DR, SIEM and Kubernetes HA |
| **13** | **Verified-work economics, Executive KPIs, Department scorecards, Agent economics, SLA, billing meters and Industry Packs** |

## Phase 13 — Executive & Business Layer

### Verified business outcomes

Evaluation Runs are synchronized into tenant-owned business outcome records:

```text
PASS  → VERIFIED
WARN  → REVIEW
FAIL  → FAILED
ERROR → FAILED
```

Each outcome can contain:

- Quality score and evidence count
- Baseline versus actual duration
- Hours saved
- Baseline versus actual cost
- Cost saved
- Attributed revenue value
- SLA target and compliance
- Department and Agent attribution
- Evaluation result hash
- Measurement assumptions

Automatic records are marked `ESTIMATED`. Confirmed finance or operational values can be entered as `MANUAL`; the worker will not overwrite them.

### Executive dashboard

The dashboard provides:

- Verified outcome count and verification rate
- Average quality
- Evidence count
- Hours and cost saved
- Revenue value and total value created
- Value-to-cost ratio
- SLA compliance
- Department scorecards
- Agent economics
- Daily value trend
- Top verified outcomes

### Integrity-hashed snapshots

Executive snapshots preserve a fixed period scorecard with a SHA-256 integrity hash for board packs, reports and audit references.

### Usage and billing

Initial tenant meters:

```text
api_requests
runtime_dispatches
external_tasks
sop_runs
backup_runs
verified_outcomes
pack_installs
```

Seeded plans:

- Team
- Enterprise
- Sovereign

Billing output is an operational estimate; it does not calculate tax, discounts, support retainers or infrastructure pass-through.

### Industry Packs

Published manifests:

- Government Document Operations
- IDC & SOC Incident Command
- AI CFO Office
- Customer Support Operations

Installation records a governed tenant manifest. It does not silently create credentials or activate external connectors.

## Phase 12 — Enterprise Platform

Each Enterprise Tenant has:

- Tenant key, slug and lifecycle status
- Data region and deployment namespace
- Row, schema or database isolation policy
- Agent and concurrent-task quotas
- Requests-per-minute limit
- Object-storage bucket and encryption-key reference
- Retention policy and air-gap mode

BeezaOffice accepts:

```text
BEEZA_AUTH_TOKEN     bootstrap / private operator token
bzsess_...           short-lived OIDC-backed enterprise session
bzk_...              tenant-scoped machine API key
```

API keys are displayed once. The database stores only the hash, prefix, tenant, identity, scopes, expiry and rate limit.

Tenant isolation is enforced for Missions, Registry, Collaboration, Dispatch, Protocol events and SOP ledgers.

## Backup, DR and Kubernetes

Backup control-plane records are executed by an approved external runner:

```text
Backup request
→ pg_dump + Redis RDB + evidence/configuration copy
→ checksum
→ immutable S3/MinIO destination
→ governed completion callback
→ restore exercise
```

Scripts:

```text
deploy/backup/run-backup.sh
deploy/backup/restore-backup.sh
```

Kubernetes baseline:

```text
deploy/k8s/beezaoffice.yaml
```

It provides three replicas, rolling updates, probes, PodDisruptionBudget, HPA, non-root/read-only security context, topology spreading and NetworkPolicy. PostgreSQL HA, Redis HA and object storage remain external platform dependencies.

## Quick deploy

```bash
cp .env.example .env
nano .env

docker compose -f compose.yml up -d --build --force-recreate
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f beezaoffice
```

Required production changes:

```env
POSTGRES_PASSWORD=SET_A_STRONG_PASSWORD
DATABASE_URL=postgresql+psycopg://beeza:THE_SAME_PASSWORD@postgres:5432/beezaoffice
BEEZA_AUTH_TOKEN=SET_A_LONG_RANDOM_TOKEN
BEEZA_PUBLIC_URL=https://beeza.example.com
BEEZA_DEFAULT_TENANT=tenant:beeza
```

Business configuration:

```env
BEEZA_BUSINESS_ENABLED=true
BEEZA_BUSINESS_INTERVAL_SECONDS=60
BEEZA_DEFAULT_LABOR_RATE_USD=30
BEEZA_BILLING_CURRENCY=USD
```

Enterprise storage configuration:

```env
BEEZA_OBJECT_STORE_ENDPOINT=https://minio.example.com
BEEZA_OBJECT_STORE_BUCKET=beeza-evidence
BEEZA_BACKUP_BUCKET=beeza-backups
BEEZA_BACKUP_ENCRYPTION_KEY_REF=vault://beeza/backup-key
BEEZA_MCP_ALLOWED_ORIGINS=https://console.example.com
```

## Executive and Business API

```text
GET  /api/business/status
POST /api/business/sync

GET  /api/business/executive?days=30
GET  /api/business/departments?days=30
GET  /api/business/agents?days=30
GET  /api/business/outcomes
POST /api/business/outcomes

GET  /api/business/snapshots
POST /api/business/snapshots

GET  /api/business/plans
GET  /api/business/billing
GET  /api/business/usage
POST /api/business/subscription

GET  /api/business/industry-packs
POST /api/business/industry-packs/{pack_key}/install
```

## Enterprise API

```text
GET  /api/enterprise/status
GET  /api/enterprise/tenants
POST /api/enterprise/tenants

GET  /api/enterprise/identity-providers
POST /api/enterprise/identity-providers
POST /api/enterprise/identity-providers/{provider_key}/discover
POST /enterprise/sso/oidc/exchange

GET    /api/enterprise/api-keys
POST   /api/enterprise/api-keys
DELETE /api/enterprise/api-keys/{key_id}

GET  /api/enterprise/sites
GET  /api/enterprise/backup/plans
POST /api/enterprise/backup/plans
GET  /api/enterprise/backup/runs
POST /api/enterprise/backup/plans/{plan_key}/runs
POST /api/enterprise/backup/runs/{run_key}/complete

GET  /api/enterprise/siem/sinks
POST /api/enterprise/siem/sinks
GET  /api/enterprise/siem/export
POST /api/enterprise/siem/sinks/{sink_key}/checkpoint
```

## Protocol endpoints

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

## Health and metrics

```text
GET /health/live
GET /health/ready
GET /metrics
GET /api/health
```

Phase 13 Prometheus metrics include:

```text
beeza_business_outcomes_total
beeza_business_verified_outcomes
beeza_business_hours_saved
beeza_business_value_created_usd
beeza_business_sla_compliance_ratio
beeza_business_installed_packs
beeza_business_active_subscriptions
```

## Runtime configuration

```env
OPENCLAW_BASE_URL=http://openclaw-host:18789
OPENCLAW_AUTH_TOKEN=
OPENCLAW_AGENT_TARGET=openclaw/default

CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=
HERMES_MODEL=hermes-agent

THCLAW_BASE_URL=http://thclaws-host:7878
THCLAW_AUTH_TOKEN=
THCLAW_MODEL=
THCLAW_WORKSPACE_DIR=
```

## Architecture

```text
Enterprise Identity / API Key
        ↓ tenant + quota + rate limit
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
Executive KPI / Department / Agent Economics / Billing / SIEM
```

## Measurement boundary

- Automatically calculated time and cost values are estimates unless manually confirmed.
- Revenue attribution requires explicit business input.
- Evaluation quality does not independently prove financial value.
- Billing output is an estimate, not a legally binding invoice.
- Industry Packs are governed manifests until their connectors and SOPs are implemented and verified.
- Production still requires real HA databases, TLS, KMS/Vault, object lock, restore drills, image signing and capacity testing.

Detailed architecture:

- `docs/PHASE-12-ENTERPRISE-PLATFORM.md`
- `docs/PHASE-13-EXECUTIVE-BUSINESS.md`

## Next phase

**Phase 14 — Commercial Productization:** tenant onboarding, contract entitlements, license enforcement, white-label branding, pack publishing workflow, signed releases and deployment installer.
