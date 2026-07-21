# BeezaOffice

**AI Workforce Operating System** for operating 10–1,000 governed AI agents across private, enterprise and sovereign environments.

BeezaOffice is the command, governance, evidence and commercial control plane above OpenClaw, CherryAgent, Hermes Agent and thClaws. It turns agent work into durable missions, verified outcomes and measurable business value.

Current application version: **0.15.0**.

## Platform

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
| 12 | Multi-tenant Enterprise Platform, OIDC, scoped API keys, rate limits, backup/DR, SIEM and Kubernetes HA |
| 13 | Verified-work economics, Executive KPIs, Department scorecards, Agent economics, SLA, billing and Industry Packs |
| **14** | **Tenant onboarding, signed licenses, contract entitlements, quota enforcement, deployment activation, white label, signed releases and production installer** |

## Architecture

```text
Enterprise Identity / API Key
        ↓ tenant + rate limit
Commercial License ∩ Contract Entitlement
        ↓ feature + quota enforcement
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
Executive KPI / Billing / SIEM / Commercial Release
```

## Phase 14 — Commercial Productization

### Signed deployment licenses

BeezaOffice accepts asymmetric JWT licenses bound to a Tenant and Deployment ID.

```env
BEEZA_LICENSE_MODE=development  # local unrestricted seed
BEEZA_LICENSE_MODE=warn         # allow with warning headers
BEEZA_LICENSE_MODE=enforce      # block unlicensed execution

BEEZA_DEPLOYMENT_ID=deployment:customer-primary
BEEZA_LICENSE_ISSUER=beezaoffice-license
BEEZA_LICENSE_AUDIENCE=beezaoffice
BEEZA_LICENSE_ALGORITHMS=EdDSA,RS256,ES256
BEEZA_LICENSE_PUBLIC_KEY=
BEEZA_LICENSE_TOKEN=
```

Production should use `enforce`. The application stores only the token SHA-256 hash and verified claims; the raw token is not persisted.

Generate offline Ed25519 keys:

```bash
python deploy/license/generate-keys.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --public-key beeza-license-public.pem
```

Issue a deployment-bound license:

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

### Contract and license intersection

Effective access is the intersection of:

```text
Active Phase 13 subscription
∩
Verified signed license
```

Effective quotas use the lower positive limit from both sources.

| Plan | Agents | Concurrent work | Tenants | Deployments |
|---|---:|---:|---:|---:|
| Team | 50 | 20 | 1 | 1 |
| Enterprise | 500 | 100 | 10 | 4 |
| Sovereign | 1,000 | 200 | 50 | 20 |

Enforced feature keys include:

```text
core.missions
collaboration
meetings
registry
scheduler
evaluation
sop
protocol
runtime.dispatch
enterprise
business
marketplace
white_label
backup_dr
siem
metrics
kubernetes
```

### Tenant onboarding

```text
organization
→ deployment
→ identity
→ runtime
→ governance
→ backup
→ verification
→ go_live
```

Each step records completion, note, actor and timestamp. Production readiness requires completed onboarding, an active license and an active Deployment.

### White label

Each Tenant can configure:

- Product and company name
- Logo and favicon
- Primary, accent and background colors
- Custom domain
- Support, privacy and terms URLs
- Locale and outbound email identity

The browser applies the Tenant profile to the title, sidebar identity, logo mark and UI variables. In enforced mode, edits require `white_label` entitlement.

### Deployment activation

Deployment records track:

- Deployment ID and fingerprint
- Environment, site and hostname
- Application version and image digest
- License association
- Status and heartbeat timestamp

Agent and Deployment registration, licensed features and concurrent work are quota-controlled.

### Signed releases

`.github/workflows/release.yml` runs on `v*` tags and:

1. Builds and pushes the container to GHCR.
2. Generates SBOM and provenance attestations.
3. Signs the immutable image digest with Cosign and GitHub OIDC.
4. Verifies the signature inside the workflow.
5. Produces a publishable release manifest, checksum and installer command.

The runtime seeds `0.15.0` as `UNSIGNED`. A release becomes `PUBLISHED` only after a verified manifest is registered through:

```text
POST /api/commercial/releases/publish
```

## Production installer

Files:

```text
deploy/install/install.sh
deploy/install/compose.production.yml
```

The installer requires:

- Docker Compose v2
- Digest-pinned container image
- Cosign verification unless explicitly bypassed
- Production license configuration

It generates protected random database, platform and metrics secrets, preserves existing configuration during upgrades, starts durable PostgreSQL/Redis services and waits for `/health/ready`.

Example from a signed release artifact:

```bash
BEEZA_IMAGE=ghcr.io/paddman/beezaoffice:0.15.0@sha256:... \
BEEZA_COSIGN_IDENTITY=https://github.com/paddman/Beezaoffice/.github/workflows/release.yml@refs/tags/v0.15.0 \
BEEZA_LICENSE_PUBLIC_KEY="$(awk '{printf "%s\\n",$0}' beeza-license-public.pem)" \
BEEZA_LICENSE_TOKEN="$(cat customer-a.jwt)" \
sh deploy/install/install.sh
```

The default bind address is `127.0.0.1:8080`; use an approved TLS reverse proxy or ingress for external access.

## Local development

```bash
cp .env.example .env
nano .env

docker compose -f compose.yml up -d --build --force-recreate
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f beezaoffice
```

The example environment uses `BEEZA_LICENSE_MODE=development` so local development remains usable without a commercial token.

## Commercial API

```text
GET  /api/commercial/status

GET  /api/commercial/onboarding
POST /api/commercial/onboarding
POST /api/commercial/onboarding/{key}/advance

GET  /api/commercial/license
POST /api/commercial/license/import
POST /api/commercial/license/verify
GET  /api/commercial/entitlements

GET /api/commercial/brand
PUT /api/commercial/brand

GET  /api/commercial/deployments
POST /api/commercial/deployments
POST /api/commercial/deployments/{key}/heartbeat

GET  /api/commercial/releases
POST /api/commercial/releases/publish
GET  /api/commercial/installer-config
```

## Business API

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
GET  /api/enterprise/backup/plans
POST /api/enterprise/backup/plans/{plan_key}/runs
GET  /api/enterprise/siem/export
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
GET /api/health
GET /metrics     Authorization: Bearer $BEEZA_METRICS_TOKEN
```

Phase 14 metrics include:

```text
beeza_commercial_active_licenses
beeza_commercial_active_deployments
beeza_commercial_completed_onboarding
beeza_commercial_published_releases
```

## Production boundary

- `development` and `warn` are not production license-enforcement modes.
- The private signing key must remain offline or inside an approved HSM/KMS signer.
- Database administrators can alter local data; protect database and audit access.
- A release manifest does not prove a signature by itself; verify the OCI digest and Cosign identity.
- Custom domains still require DNS, TLS certificates and ingress configuration.
- Billing remains an operational estimate, not a legally binding invoice.
- Automatically calculated business time and cost remain estimates unless manually confirmed.
- Production still requires HA PostgreSQL/Redis, object lock, restore drills, capacity testing and incident runbooks.

Detailed architecture:

- `docs/PHASE-12-ENTERPRISE-PLATFORM.md`
- `docs/PHASE-13-EXECUTIVE-BUSINESS.md`
- `docs/PHASE-14-COMMERCIAL-PRODUCTIZATION.md`

After Phase 14, the numbered build roadmap is complete. The next work is **pilot deployment, real runtime integration, load testing, security review and customer validation**.
