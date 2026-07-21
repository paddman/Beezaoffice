# Phase 14 — Commercial Productization

Phase 14 packages BeezaOffice as a governed commercial product. It adds Tenant onboarding, signed deployment-bound licenses, contract entitlements, quota enforcement, deployment activation, white-label branding, signed release manifests and a production installer.

## Commercial boundary

```text
Active commercial contract
        ↓
Billing-plan entitlements
        ∩
Signed deployment license
        ↓
Effective features and lower quotas
        ↓
Tenant isolation + Governance
        ↓
Mission / Agent / Runtime / SOP / Protocol / Enterprise / Business execution
```

A contract cannot enable a feature absent from the signed license. A license cannot enable a feature excluded by the active contract. Effective quotas use the lower positive value from both sources.

## License modes

```env
BEEZA_LICENSE_MODE=development
BEEZA_LICENSE_MODE=warn
BEEZA_LICENSE_MODE=enforce
```

- `development` seeds a local non-production Sovereign development license.
- `warn` permits execution without a valid license and emits warning headers.
- `enforce` returns HTTP `402` for licensed execution without a valid license.

The production installer defaults to `enforce`. A stored `DEVELOPMENT` license is ignored after the runtime is changed to `warn` or `enforce`.

## Signed license format

The included issuer uses Ed25519 and `EdDSA`. Runtime validation also supports configured `RS256` and `ES256` public keys.

Required claims:

```text
iss
aud
sub
jti
iat
nbf
exp
tenant_key
deployment_id
plan_key
features
limits
```

Validation checks:

- Signature algorithm allowlist
- Issuer and audience
- Issue time, activation time and expiration
- Tenant and Deployment binding
- Supported Plan
- Feature subset of that Plan
- Quota keys and maximum values for that Plan
- Token replay across another Tenant or Deployment

The database stores the token SHA-256 hash and verified claims, not the raw JWT.

### Generate offline keys

```bash
python deploy/license/generate-keys.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --public-key beeza-license-public.pem
```

The private key must remain offline or inside an approved HSM/KMS signer. Only the public key is deployed to BeezaOffice.

### Issue a license

```bash
python deploy/license/issue-license.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --tenant-key tenant:customer-a \
  --deployment-id deployment:customer-a-primary \
  --plan-key plan:enterprise \
  --days 365 \
  --customer-name "Customer A" \
  --contract-reference "CONTRACT-2026-001" \
  --output customer-a.jwt
```

### Verify offline

```bash
python deploy/license/verify-license.py \
  --public-key beeza-license-public.pem \
  --token customer-a.jwt \
  --tenant-key tenant:customer-a \
  --deployment-id deployment:customer-a-primary
```

### Activate

```text
POST /api/commercial/license/import
```

```json
{
  "token": "eyJ..."
}
```

Import performs full cryptographic validation. Re-import performs signature validation again. The lightweight status check validates stored state and expiry; it does not possess the raw token needed to repeat signature verification.

## Contract entitlements and quotas

| Plan | Agents | Concurrent work | Tenants | Deployments |
|---|---:|---:|---:|---:|
| Team | 50 | 20 | 1 | 1 |
| Enterprise | 500 | 100 | 10 | 4 |
| Sovereign | 1,000 | 200 | 50 | 20 |

Feature examples:

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

Contract and License entitlement rows coexist by `Tenant + Feature + Source`. Startup includes a safe PostgreSQL constraint migration for installations created by an earlier Phase 14 build.

Enforcement covers:

- Licensed operational write paths
- Agent registration limit
- Active-work concurrency limit
- Enterprise Tenant count
- Deployment count
- White-label access

Read-only diagnostics and Commercial recovery APIs remain available through normal Governance permissions.

## Tenant request resolution

Commercial enforcement resolves the active Tenant before License middleware by checking:

1. OIDC-backed enterprise session
2. Scoped API key
3. Governed identity
4. Explicit Tenant switch when the identity has `enterprise:tenant:manage`
5. Default Tenant

Phase 12 performs the authoritative authentication and Tenant-isolation check afterward.

## Tenant onboarding

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

Each step stores completion state, operator note, actor and timestamp.

```text
GET  /api/commercial/onboarding
POST /api/commercial/onboarding
POST /api/commercial/onboarding/{onboarding_key}/advance
```

## White label

Tenant branding supports:

- Product and company name
- Logo and favicon URLs
- Primary, accent and background colors
- Custom domain
- Support, Privacy and Terms URLs
- Locale and outbound email identity

```text
GET /api/commercial/brand
PUT /api/commercial/brand
```

The browser applies the profile to the page title, sidebar identity, logo and CSS variables. Enforced deployments require the `white_label` feature.

## Deployment activation

Deployment records contain:

- Deployment ID and fingerprint
- Environment, site and hostname
- Application version
- Container image digest
- License association
- Heartbeat state and timestamp

```text
GET  /api/commercial/deployments
POST /api/commercial/deployments
POST /api/commercial/deployments/{deployment_key}/heartbeat
```

The production installer reports its host fingerprint and verified image digest after startup.

## Signed release pipeline

`.github/workflows/release.yml` runs for `v*` tags:

1. Build and push the container to GHCR.
2. Generate SBOM and provenance attestations.
3. Sign the immutable image digest with Cosign and GitHub OIDC.
4. Verify the signature in the workflow.
5. Produce `release-manifest.json`, its checksum and installation instructions.

The runtime seeds release `0.15.0` as `UNSIGNED`. A release becomes `PUBLISHED` after a verified manifest is registered:

```text
POST /api/commercial/releases/publish
```

The endpoint records:

- Image reference and SHA-256 digest
- Signature reference
- SBOM reference
- Provenance reference
- Source commit
- Certificate identity and OIDC issuer

It records evidence; it does not execute Cosign itself. CI and the production installer perform signature verification.

## Production readiness

`production_ready=true` requires all of the following:

- `BEEZA_LICENSE_MODE=enforce`
- Completed onboarding
- Active signed license
- Active Deployment
- Published release with digest, signature, SBOM and provenance references
- Deployment-reported image digest equal to the published release digest

This prevents an unsigned or mismatched image from being reported as commercially ready.

## Production installer

```text
deploy/install/install.sh
deploy/install/compose.production.yml
```

The installer:

- Requires Docker Compose v2
- Requires a digest-pinned image
- Verifies Cosign identity unless explicitly bypassed
- Generates protected PostgreSQL, platform and metrics secrets
- Defaults to License enforcement
- Preserves an existing `.env` on upgrade
- Uses a read-only application container with `no-new-privileges`
- Starts durable PostgreSQL and Redis volumes
- Waits for `/health/ready`
- Registers Deployment fingerprint and image digest

Example:

```bash
BEEZA_IMAGE=ghcr.io/paddman/beezaoffice:0.15.0@sha256:... \
BEEZA_COSIGN_IDENTITY=https://github.com/paddman/Beezaoffice/.github/workflows/release.yml@refs/tags/v0.15.0 \
BEEZA_LICENSE_PUBLIC_KEY="$(awk '{printf "%s\\n",$0}' beeza-license-public.pem)" \
BEEZA_LICENSE_TOKEN="$(cat customer-a.jwt)" \
sh deploy/install/install.sh
```

The default bind address is `127.0.0.1:8080`. External access requires an approved TLS reverse proxy or ingress.

Kubernetes commercial settings example:

```text
deploy/k8s/phase14-commercial.example.yaml
```

Pin the image by digest and move License secrets to the approved external-secret system before applying it.

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

## Governance permissions

```text
commercial:read
commercial:onboarding:manage
commercial:license:manage
commercial:brand:manage
commercial:deployment:manage
commercial:release:read
commercial:release:publish
```

License, Brand, Deployment and Release changes are execution-controlled Governance actions.

## Observability

```text
beeza_commercial_active_licenses
beeza_commercial_active_deployments
beeza_commercial_completed_onboarding
beeza_commercial_published_releases
```

`/api/health` reports Phase 14, License state, Deployment ID and signed-release state. Active-license metrics count only currently valid licenses.

## CI verification

CI now performs:

- Python compilation for Phase 1–14
- Browser JavaScript checks
- Installer and Compose syntax checks
- Container build
- Ed25519 license signing and verification self-test
- Deployment-binding rejection test
- Plan feature-escalation rejection test
- Plan quota-escalation rejection test
- Route, Permission, Schema and Commercial smoke tests
- SPDX dependency inventory generation

## Production boundary

- `development` and `warn` are not production enforcement modes.
- Database administrators can alter local state; protect PostgreSQL and Audit access.
- A manifest row alone does not prove image authenticity; verify OCI digest and Cosign identity.
- Installer bypass flags are for controlled recovery and should be prohibited by policy.
- Custom domains require DNS, TLS and ingress configuration.
- Billing remains an operational estimate, not a legally binding invoice.
- Production still requires HA databases, object lock, restore drills, load testing, security review and incident runbooks.
