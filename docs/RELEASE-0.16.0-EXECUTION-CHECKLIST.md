# BeezaOffice 0.16.0 — Execution Checklist

This checklist separates implemented capability from evidence that must be produced on the real Pilot environment.

## Implemented on `main`

- Application version source and `VERSION` file set to `0.16.0`
- Pilot Program and Gate Evidence database models
- Alembic head `20260722_0002`
- Pilot Operations API and dashboard
- Signed-License enforce-mode Pilot Compose
- Automated two-Tenant integration gate
- Runtime adapter contract simulator
- Thresholded load test
- HTTP security review
- Destructive PostgreSQL restore verification
- Real Runtime E2E runner
- First-customer acceptance runner
- Signed remote deployment workflow
- Protected recovery/isolation workflow
- Cosign-verified promotion workflow
- Optional stable tag promotion after 10/10 gates and human acceptance

## GitHub Environment

Create the protected Environment:

```text
pilot-production
```

Recommended rules:

- Required deployment reviewer
- Required promotion reviewer
- Restrict deployment to `main`
- Rotate secrets when the Pilot closes

## Required secrets

```text
PILOT_AUTH_TOKEN
PILOT_SSH_PRIVATE_KEY
PILOT_SSH_KNOWN_HOSTS
PILOT_ENV_B64
PILOT_SECONDARY_LICENSE_TOKEN
```

### `PILOT_AUTH_TOKEN`

Must equal `BEEZA_AUTH_TOKEN` in the deployed Pilot environment.

### `PILOT_SSH_KNOWN_HOSTS`

Pin the real SSH host key. Do not obtain it dynamically inside the deployment workflow.

Example collection from a trusted administrative network:

```bash
ssh-keyscan -p 22 -H PILOT_HOST > pilot_known_hosts
ssh-keygen -lf pilot_known_hosts
```

Verify the fingerprint through a separate trusted channel before storing it as the secret.

### `PILOT_ENV_B64`

Base64-encoded Pilot environment file. It must include:

```env
APP_ENV=production
BEEZA_APP_VERSION=0.16.0
BEEZA_RELEASE_CHANNEL=pilot
BEEZA_SCHEMA_STRICT=true
BEEZA_FORCE_HTTPS=true
BEEZA_LICENSE_MODE=enforce
BEEZA_DEPLOYMENT_ID=deployment:CUSTOMER-pilot
BEEZA_LICENSE_PUBLIC_KEY=...
BEEZA_LICENSE_TOKEN=...
BEEZA_AUTH_TOKEN=...
BEEZA_METRICS_TOKEN=...
DATABASE_URL=...
REDIS_URL=...
OPENCLAW_BASE_URL=...
OPENCLAW_AUTH_TOKEN=...
CHERRYAGENT_BASE_URL=...
CHERRYAGENT_AUTH_TOKEN=...
HERMES_BASE_URL=...
HERMES_AUTH_TOKEN=...
THCLAW_BASE_URL=...
THCLAW_AUTH_TOKEN=...
```

Create the encoded value locally:

```bash
base64 -w0 pilot.env
```

### `PILOT_SECONDARY_LICENSE_TOKEN`

A signed License for a temporary secondary Tenant using the same Pilot Deployment ID. It is used only to prove cross-Tenant isolation on the real environment.

## Execution order

### 1. Run repository gates

Workflows triggered by `main`:

```text
CI
Pilot Gate 0.16.0
```

Expected integration Pilot state:

```text
8/10 automated gates PASS
release_signed PENDING
customer_acceptance PENDING
production_promotion_allowed=false
```

The Runtime simulator proves adapter contracts only. It is not real Runtime evidence.

### 2. Create signed release candidate

```bash
git checkout main
git pull origin main
git tag -a v0.16.0-rc.1 -m "BeezaOffice 0.16.0 Release Candidate 1"
git push origin v0.16.0-rc.1
```

The Signed Release workflow generates:

- Digest-pinned GHCR image
- Cosign signature
- SBOM
- Provenance
- Release Manifest
- Installer command

### 3. Deploy the signed Pilot

Run:

```text
Deploy Signed Pilot
```

Inputs:

- Pilot host, SSH user and port
- Signed digest-pinned RC image
- Expected Cosign certificate identity
- HTTPS Pilot URL

The workflow verifies the signature on the Pilot host, performs a pre-migration backup, applies Alembic migrations and verifies version `0.16.0` in License `enforce` mode.

### 4. Record real recovery and isolation evidence

Run:

```text
Pilot Recovery and Isolation
```

Confirmation:

```text
RESTORE-VERIFY-0.16.0
```

The workflow:

- Validates signed License and strict schema
- Imports the secondary Tenant License
- Verifies cross-Tenant Mission isolation
- Dumps the live PostgreSQL database
- Restores into an isolated temporary verification database
- Compares durable record counts
- Tests Alembic downgrade/upgrade on the restored copy
- Drops the temporary verification database
- Records five real Pilot gates

### 5. Run real Runtime and customer validation

Run:

```text
Pilot Validation and Promotion
```

Required inputs:

- HTTPS Pilot URL
- Primary Tenant and Pilot key
- Real Runtime keys
- Signed digest-pinned RC image
- Expected Cosign identity
- Customer organization
- Named customer representative
- Acceptance note

The workflow independently verifies the Cosign signature, confirms that the active Deployment reports the same image digest, executes real Runtime E2E, security and load tests, runs the customer journey and records human acceptance.

### 6. Promote stable tag

Set:

```text
promote_stable_tag=true
```

Promotion is permitted only when:

```text
10/10 gates PASS
Pilot status = AWAITING_ACCEPTANCE
Executive decision = ACCEPT
Final Pilot status = ACCEPTED
```

The workflow creates and pushes:

```text
v0.16.0
```

The stable tag triggers the Signed Release workflow again, producing the stable signed image and Manifest.

## Evidence that must not be fabricated

These remain incomplete until the corresponding workflow succeeds:

- Real host deployment
- Permanent Customer License issuance
- Real OpenClaw, CherryAgent, Hermes and thClaws E2E
- Real backup/restore on the Pilot host
- Production load and security results
- Named customer acceptance
- Stable `v0.16.0` tag

Repository source completion is not proof that these operational events occurred.
