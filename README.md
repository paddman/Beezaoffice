# BeezaOffice

**AI Workforce Operating System** for operating 10–1,000 governed AI agents across private, sovereign and enterprise environments.

BeezaOffice is the command and governance plane above OpenClaw, CherryAgent, Hermes Agent and thClaws. It turns agent work into durable missions with collaboration, meetings, intelligent routing, evidence verification, reusable SOPs, standard protocols and enterprise controls.

## Current platform

| Phase | Capability |
|---:|---|
| 2 | Runtime dispatch, synchronization, remote output, safe stop and approvals |
| 3 | Durable runtime-event stream and mission SSE |
| 4 | Typed Collaboration Bus, dependencies, mailbox, retry and escalation |
| 5 | Structured agent meetings, bounded rounds and human decisions |
| 6 | Identity, RBAC, clearance, policy, budget, approvals, kill switch and hash-chained audit |
| 7 | Agent Registry, organization graph, skills, capacity, reliability and delegation |
| 8 | Intelligent Agent/Runtime/Model routing, cost control, backpressure and failover |
| 9 | Evidence evaluation, acceptance checks, provenance, replay and quality scoring |
| 10 | Versioned SOP Builder, approval nodes, verification gates and rollback |
| 11 | A2A, MCP tools subset, OpenAI-compatible API, signed webhooks and protocol events |
| **12** | **Multi-tenant enterprise platform, OIDC sessions, scoped API keys, rate limits, backup/DR, SIEM, Kubernetes HA and observability** |

## Phase 12 — Enterprise Platform

### Multi-tenant control plane

Each tenant has:

- Tenant key, slug and lifecycle status
- Data region and deployment namespace
- Row, schema or database isolation policy
- Agent and concurrent-task quotas
- Requests-per-minute limit
- Object-storage bucket and encryption-key reference
- Retention policy and air-gap mode

Existing resources are assigned to `tenant:beeza` on first startup. New Mission, Protocol and SOP resources inherit the active request tenant.

### Enterprise authentication

BeezaOffice accepts three credential types:

```text
BEEZA_AUTH_TOKEN     bootstrap / private operator token
bzsess_...           short-lived OIDC-backed enterprise session
bzk_...              tenant-scoped machine API key
```

OIDC exchange verifies issuer, audience, expiry, issue time and the configured JWKS signing key. Auto-provisioned users receive a governed identity and tenant-scoped role binding.

API keys are displayed once. Only the SHA-256 hash, prefix, tenant, identity, scopes, rate limit and expiry are stored.

### Tenant isolation and rate limiting

```text
Credential
→ resolve identity and tenant
→ enforce API-key scope
→ Redis tenant/identity rate limit
→ verify resource ownership
→ Phase 6 Governance
→ execute request
```

Mission list/create/detail and Protocol task lists are tenant-aware. Mission-linked operations return `404` when the active tenant does not own the resource.

### Backup and DR

Backup plans and runs are tracked in the control plane. Privileged backup commands execute through an approved external runner rather than inside the web process.

```text
Backup request
→ signed manifest
→ pg_dump + Redis RDB + evidence/config copy
→ immutable S3/MinIO destination
→ governed completion callback
→ restore exercise
```

Scripts:

```text
deploy/backup/run-backup.sh
deploy/backup/restore-backup.sh
```

A requested backup is not considered verified until the executor reports `COMPLETED` and the archive checksum is retained.

### SIEM and audit export

Tenant-scoped audit records can be exported using an at-least-once cursor while preserving the audit hash chain.

```text
GET  /api/enterprise/siem/export?after_id=0&limit=500
POST /api/enterprise/siem/sinks/{sink_key}/checkpoint?last_audit_id=...
```

### HA and Kubernetes

`deploy/k8s/beezaoffice.yaml` provides a production baseline with:

- Three control-plane replicas
- Rolling updates
- Liveness and readiness probes
- Pod disruption budget
- Horizontal autoscaling
- Non-root/read-only security context
- Default-deny NetworkPolicy
- Topology spreading
- External PostgreSQL HA, Redis HA and object-storage references

### Observability and supply chain

```text
GET /health/live
GET /health/ready
GET /metrics
GET /api/health
```

CI compiles all Phase 1–12 modules, checks browser JavaScript, builds the image, runs enterprise smoke tests and publishes an SPDX 2.3 dependency inventory artifact.

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

For OIDC, backup and object storage also configure:

```env
BEEZA_OBJECT_STORE_ENDPOINT=https://minio.example.com
BEEZA_OBJECT_STORE_BUCKET=beeza-evidence
BEEZA_BACKUP_BUCKET=beeza-backups
BEEZA_BACKUP_ENCRYPTION_KEY_REF=vault://beeza/backup-key
BEEZA_MCP_ALLOWED_ORIGINS=https://console.example.com
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
Verified Outcome / SIEM / Executive Reporting
```

## Enterprise boundary

Phase 12 provides the software control-plane baseline. Production readiness still requires site-owned infrastructure and operations:

- Real PostgreSQL and Redis HA
- TLS ingress and certificate rotation
- KMS/HSM or Vault-backed key references
- S3/MinIO object lock
- OIDC/SAML/LDAP provider configuration
- Backup restore drills and DR exercises
- Container signing identity and admission policy
- Capacity testing and incident runbooks

Detailed architecture: `docs/PHASE-12-ENTERPRISE-PLATFORM.md`.

## Next phase

**Phase 13 — Executive & Business Layer:** outcome KPIs, verified-work economics, cost savings, departmental scorecards, billing, industry packs and marketplace packaging.
