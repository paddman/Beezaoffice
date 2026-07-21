# Phase 12 — Enterprise Platform

Phase 12 turns BeezaOffice from a single private control plane into an enterprise deployment baseline with governed tenants, federated identity, scoped machine credentials, rate limiting, backup/DR contracts, SIEM export, Kubernetes HA assets and production health endpoints.

## Enterprise request boundary

```text
Human / Agent / Service / External Client
        ↓
Platform token / OIDC session / Scoped API key
        ↓
Tenant resolution + rate limit
        ↓
Resource tenant isolation
        ↓
Phase 6 Governance
        ↓
Mission / Scheduler / Runtime / Evaluation / SOP / Protocol
```

The default tenant is `tenant:beeza`. Existing Phase 1–11 resources are scoped to this tenant on first startup.

## Tenant model

Each enterprise tenant contains:

- Tenant key and slug
- Lifecycle status
- Isolation mode: `ROW`, `SCHEMA` or `DATABASE`
- Data region and Kubernetes namespace
- Object-storage bucket
- Encryption-key reference
- Agent and concurrent-task quotas
- Requests-per-minute limit
- Retention period
- Air-gap mode

Phase 12 enforces row-level resource ownership for mission and protocol task access. The model includes schema/database isolation modes for later physical isolation deployments.

## Enterprise authentication

### Platform operator token

The existing `BEEZA_AUTH_TOKEN` remains available for bootstrap, break-glass and private deployment administration.

### OIDC federation

An enabled OIDC provider stores:

- Issuer and client/audience
- JWKS URI
- Authorization and token endpoints
- Allowed signing algorithms
- Subject, email and group claim names
- Group-to-role map
- Default governed role
- Auto-provisioning policy

Exchange endpoint:

```text
POST /enterprise/sso/oidc/exchange
```

The ID token is verified against issuer, audience, expiry and the provider JWKS. Successful exchange provisions or updates a tenant membership and returns a short-lived `bzsess_...` token. Plain session tokens are never stored; only SHA-256 hashes are retained.

SAML and LDAP provider records are supported as enterprise configuration inventory. Full SAML assertion and LDAP bind flows are deferred to provider-specific adapters.

### Scoped API keys

API keys begin with `bzk_` and are shown once. The database stores only the SHA-256 hash, prefix, tenant, identity, permission patterns, expiry and per-key rate limit.

API-key permission scopes are evaluated before normal Governance RBAC. A key cannot grant more authority than its linked identity already has.

## Tenant isolation

`enterprise_resource_scopes` maps resource keys to tenants.

```text
mission          → tenant
protocol_task    → tenant
sop_template     → tenant
sop_run          → tenant
```

Mission list, create and detail routes are tenant-aware. Protocol task lists are filtered by tenant. Mission-linked dispatches, Collaboration tasks and SOP runs are denied with `404` when the request tenant does not own the underlying mission.

Internally generated Protocol tasks and SOP runs inherit the active request tenant through a context variable and are scoped before commit.

## Rate limiting

Rate limits use Redis fixed one-minute windows keyed by:

```text
tenant + identity + minute
```

The tenant provides the default limit. An API key can set a lower integration-specific limit. Responses include tenant and rate-limit policy headers; excess requests return HTTP `429` with `Retry-After`.

## Backup and disaster recovery

The control plane stores backup plans and runs. It does not run privileged database commands inside the web process.

```text
BeezaOffice backup request
        ↓
BackupRun REQUESTED + signed manifest/checksum
        ↓
Approved external backup executor
        ├─ pg_dump custom/compressed
        ├─ Redis RDB
        ├─ Evidence/configuration copy
        └─ S3/MinIO object lock
        ↓
Governed completion callback
```

Deployment scripts:

```text
deploy/backup/run-backup.sh
deploy/backup/restore-backup.sh
```

The restore script requires an explicit destructive confirmation and validates SHA-256 checksums before PostgreSQL restore. Redis installation remains site-orchestrated so it can be performed during a controlled maintenance restart.

A backup is considered verified only after the external executor reports `COMPLETED`. Creating a plan or requesting a run is not proof that recoverable backup data exists.

## SIEM export

The SIEM pull API exports tenant audit records while preserving:

- Audit ID and request ID
- Identity and action
- Method, path and resource
- Outcome and status
- Source IP and user agent
- Previous hash and record hash
- Timestamp and tenant

```text
GET  /api/enterprise/siem/export?after_id=0&limit=500
POST /api/enterprise/siem/sinks/{sink_key}/checkpoint?last_audit_id=...
```

The cursor is advanced only after the external SIEM confirms delivery. This provides at-least-once export behavior.

## Production health and metrics

```text
GET /health/live
GET /health/ready
GET /metrics
GET /api/health
```

`/metrics` exposes Prometheus text for tenant count, mission count, registered agents, active runtime dispatches and Protocol tasks.

## Kubernetes baseline

`deploy/k8s/beezaoffice.yaml` provides:

- Dedicated namespace and service account
- Three control-plane replicas
- Rolling update with zero planned unavailability
- Readiness and liveness probes
- Pod disruption budget
- Horizontal pod autoscaler
- Non-root, read-only container security context
- Default-deny and explicit ingress/egress NetworkPolicy
- ConfigMap and Secret templates
- Topology spreading across nodes

PostgreSQL, Redis and object storage are referenced as external HA services. They should be provided by an approved operator or managed platform rather than embedded as single-instance sidecars.

## API

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

## Permissions

```text
enterprise:read
enterprise:tenant:manage
enterprise:sso:manage
enterprise:credentials:manage
enterprise:backup:manage
enterprise:backup:run
enterprise:backup:complete
enterprise:siem:manage
enterprise:siem:operate
```

Backup execution and completion are kill-switch-controlled actions.

## CI and supply chain

CI now:

- Compiles all Phase 1–12 Python modules
- Checks all browser JavaScript
- Builds the container image
- Smoke-tests Enterprise models, routes, permissions and health endpoints
- Generates an SPDX 2.3 dependency inventory as a workflow artifact

Image signing requires the deployment organization's signing identity and registry credentials. The repository does not claim that images are signed until a production CI identity and policy are configured.

## Current boundary

- OIDC token exchange is implemented; SAML and LDAP are configuration records awaiting provider-specific adapters.
- Mission and Protocol resources are row-isolated. Physical schema/database-per-tenant deployment is represented but not automatically provisioned.
- Backup execution is intentionally external to the web process.
- Kubernetes manifests are a hardened baseline, not a replacement for site capacity planning, database operators, storage classes, ingress certificates or DR exercises.
- A DR site is not considered ready until it is registered as `DR`, reports `READY`, and a restore exercise has been completed.
