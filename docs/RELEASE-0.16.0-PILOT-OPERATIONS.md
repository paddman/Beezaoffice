# BeezaOffice 0.16.0 — Pilot Operations Release

Version `0.16.0` is the operational release after the Phase 14 product roadmap. It does not introduce Phase 15. It turns commercial readiness into an evidence-driven Pilot process.

## Release objective

```text
Build complete
→ Signed RC image
→ Licensed Pilot deployment
→ Real Runtime E2E
→ Load and security review
→ Backup and rollback proof
→ First-customer journey
→ Human acceptance
→ Stable v0.16.0 promotion
```

## Required gates

| Gate | Required evidence |
|---|---|
| `release_signed` | Immutable image digest, Cosign identity, SBOM and provenance reference |
| `license_lifecycle` | Valid signed License in `enforce` mode, Tenant and Deployment binding |
| `schema_migration` | Alembic revision `20260722_0002` in strict readiness mode |
| `tenant_isolation` | Cross-Tenant reads denied before and after database restore |
| `runtime_e2e` | Probe, Mission dispatch and evidence-backed result from every selected real Runtime |
| `backup_restore` | Destructive PostgreSQL restore with durable Mission and Pilot evidence |
| `load_test` | Error rate, p95 latency and throughput thresholds |
| `security_review` | Authentication, headers, body limit, HTTPS and Tenant-context checks |
| `upgrade_rollback` | Revision rollback/upgrade or approved release rollback with no data loss |
| `customer_acceptance` | Named human representative, acceptance note and successful customer journey |

A Pilot cannot be accepted while any required gate is not `PASS`.

## Version source

Application release identity is centralized in:

```text
app/release_version.py
```

Default values:

```text
APP_VERSION=0.16.0
RELEASE_CHANNEL=pilot
RELEASE_TAG=v0.16.0
RELEASE_NAME=Pilot Operations Release
```

The Docker runtime starts `pilot_bootstrap:app`. Commercial status, Deployment registration and Release Manifest seeding inherit the same version.

## Pilot database

Migration:

```text
app/migrations/versions/20260722_0002_pilot_operations.py
```

Tables:

```text
pilot_programs
pilot_gate_evidence
```

Evidence rows contain:

- Pilot and Gate key
- Status and source
- Human-readable summary
- Structured metrics
- Artifact reference
- Recording identity
- Start/completion timestamps
- SHA-256 integrity hash

Downgrade is deliberately non-destructive because Pilot evidence is operational audit data.

## Automated integration Pilot

Workflow:

```text
.github/workflows/pilot-gate.yml
```

This workflow is suitable for repository validation, not customer sign-off. It runs:

- Two signed ephemeral Enterprise Licenses
- Two-Tenant isolation
- PostgreSQL restore
- Alembic downgrade/upgrade
- Four adapter contracts through `pilot_mock_runtime.py`
- HTTP security checks
- Thresholded load test

The deterministic Runtime simulator validates BeezaOffice adapter contracts. It does not prove connectivity or behavior of production OpenClaw, CherryAgent, Hermes or thClaws systems.

Expected automated result:

```text
8 / 10 gates PASS
release_signed PENDING
customer_acceptance PENDING
production_promotion_allowed=false
```

## Signed RC preparation

Create an RC tag, for example:

```bash
git checkout main
git pull origin main
git tag -a v0.16.0-rc.1 -m "BeezaOffice 0.16.0 Release Candidate 1"
git push origin v0.16.0-rc.1
```

`.github/workflows/release.yml` builds, signs and verifies the digest, then produces the Release Manifest and installer command.

Do not use an unpinned tag in the Pilot installer. Use the artifact form:

```text
ghcr.io/paddman/beezaoffice:0.16.0-rc.1@sha256:...
```

## Real Pilot License

Generate the production License key pair outside the application host:

```bash
python deploy/license/generate-keys.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --public-key beeza-license-public.pem
```

Issue a Pilot License:

```bash
python deploy/license/issue-license.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --tenant-key tenant:customer-a \
  --deployment-id deployment:customer-a-pilot \
  --plan-key plan:enterprise \
  --days 90 \
  --customer-name "Customer A" \
  --contract-reference "PILOT-2026-001" \
  --output customer-a-pilot.jwt
```

Keep the private key offline. The Pilot host receives only the Public Key and signed JWT.

## GitHub Pilot environment

Create a protected GitHub Environment:

```text
pilot-production
```

Recommended protection:

- Required reviewer before deployment
- Required reviewer before stable promotion
- Restricted deployment branches
- Secret rotation after Pilot completion

### Deployment secrets

```text
PILOT_SSH_PRIVATE_KEY
PILOT_ENV_B64
```

`PILOT_ENV_B64` is a base64-encoded production environment file containing at minimum:

```env
APP_ENV=production
BEEZA_APP_VERSION=0.16.0
BEEZA_RELEASE_CHANNEL=pilot
BEEZA_SCHEMA_STRICT=true
BEEZA_FORCE_HTTPS=true
BEEZA_LICENSE_MODE=enforce
BEEZA_DEPLOYMENT_ID=deployment:customer-a-pilot
BEEZA_LICENSE_PUBLIC_KEY=...
BEEZA_LICENSE_TOKEN=...
BEEZA_AUTH_TOKEN=...
BEEZA_METRICS_TOKEN=...
DATABASE_URL=...
REDIS_URL=...
OPENCLAW_BASE_URL=...
CHERRYAGENT_BASE_URL=...
HERMES_BASE_URL=...
THCLAW_BASE_URL=...
```

Create the secret payload locally:

```bash
base64 -w0 pilot.env
```

### Validation secret

```text
PILOT_AUTH_TOKEN
```

It must match `BEEZA_AUTH_TOKEN` on the deployed Pilot environment.

## Deploy signed Pilot

Run workflow:

```text
Deploy Signed Pilot
```

Inputs:

- Pilot host and SSH user/port
- Digest-pinned RC image
- Expected Cosign certificate identity
- HTTPS Pilot URL

The remote workflow:

1. Validates inputs and secrets.
2. Uploads the installer and protected environment.
3. Verifies the signed image with Cosign on the host.
4. Creates a pre-migration PostgreSQL backup.
5. Applies Alembic revision `20260722_0002`.
6. Starts version `0.16.0` in License `enforce` mode.
7. Registers Deployment fingerprint and image digest.
8. Verifies remote readiness.

## Run real validation

Run workflow:

```text
Pilot Validation and Promotion
```

Inputs include the Pilot URL, Pilot Program key, real Runtime keys, signed RC evidence, customer name and human sign-off.

The Runtime E2E Mission is deliberately harmless:

- No external modifications
- No file writes
- No network changes
- Requires an evidence-backed response

Runtime Gate passes only when every requested Runtime returns acceptable completion evidence.

## Load gate

Repository integration threshold:

```text
20 concurrent clients
20 seconds
error rate <= 1%
p95 <= 1,500 ms
throughput >= 5 requests/sec
```

Real Pilot threshold:

```text
50 concurrent clients
60 seconds
error rate <= 1%
p95 <= 1,500 ms
throughput >= 10 requests/sec
```

These are initial Pilot thresholds, not final capacity certification for 1,000 active Agents.

## Security gate

Automated checks include:

- Protected API denies unauthenticated calls
- Invalid token denied
- CSP, frame denial, MIME sniffing protection and no-referrer headers
- Server banner disabled
- Oversized request rejected
- Tenant context preserved
- Commercial License context available

This is a baseline review. It does not replace independent penetration testing, dependency scanning, infrastructure review or compliance assessment.

## Customer acceptance

The customer journey verifies:

1. Application and Commercial status report `0.16.0`.
2. White-label profile can be configured under the licensed Plan.
3. A governed Mission can be created and retrieved.
4. The Pilot evidence ledger contains all required Gates.
5. A named representative supplies a sign-off note.

The customer gate records the representative, timestamp, Mission key, checks and artifact reference.

## Stable promotion

Stable tag creation is optional in `pilot-promotion.yml` and occurs only after:

```text
10 / 10 gates PASS
Pilot status = AWAITING_ACCEPTANCE
Executive decision = ACCEPT
Pilot status = ACCEPTED
```

Then the workflow may create:

```text
v0.16.0
```

The tag triggers the signed release workflow. The signed stable Release Manifest must still be registered in the Commercial API and its digest must match the deployed image before `production_ready=true`.

## Rollback

Application rollback procedure:

1. Preserve Pilot Evidence and audit export.
2. Stop BeezaOffice application container.
3. Restore the pre-migration database backup when schema/data rollback is required.
4. Deploy the previously verified digest-pinned image.
5. Run the matching Alembic revision.
6. Verify Tenant isolation, License state, Runtime connectivity and `/health/ready`.
7. Record `upgrade_rollback` Gate evidence and incident reference.

Never replace a failed Pilot with an unverified image tag.

## Honest status rules

Repository automation must not convert these into `PASS` without evidence:

- `release_signed`: requires a real signed image digest/reference.
- `runtime_e2e`: CI simulator evidence is not production Runtime evidence.
- `customer_acceptance`: requires a named human representative.
- Stable tag: requires explicit promotion after accepted Pilot.

Source code on `main` means the capability is implemented. It does not mean the production Pilot has already run.
