# Phase 14 — Commercial Productization

Phase 14 packages BeezaOffice as a governed commercial product. It adds tenant onboarding, signed deployment-bound licenses, contract entitlements, quota enforcement, deployment activation, white-label branding, signed release manifests and a production installer.

## Product boundary

```text
Commercial contract
        ↓
Billing plan entitlement
        ∩
Signed deployment license
        ↓
Effective feature and quota set
        ↓
Governance / Tenant isolation
        ↓
Mission, Runtime, SOP, Protocol, Enterprise and Business execution
```

A contract cannot enable a feature that is absent from the signed license. A license cannot enable a feature excluded from the active contract. Effective quotas use the lower positive limit from the contract and license.

## License modes

```env
BEEZA_LICENSE_MODE=development
BEEZA_LICENSE_MODE=warn
BEEZA_LICENSE_MODE=enforce
```

- `development`: creates a local non-production Sovereign development license and all features.
- `warn`: allows execution without an active license but adds warning headers.
- `enforce`: returns HTTP `402` for licensed execution when no valid license is active.

Production installers default to `enforce`.

## Signed license format

BeezaOffice verifies asymmetric JWT licenses. The default issuer tool uses Ed25519 / `EdDSA`.

Required claims:

```text
iss
aud
sub
jti
ıat
nbf
exp
tenant_key
deployment_id
plan_key
features
limits
```

The application stores only the token SHA-256 hash and verified claims. The raw license token is not persisted in the database.

The token is bound to `BEEZA_DEPLOYMENT_ID`; a token issued for another deployment is rejected. Reusing the same token across a different Tenant or Deployment is rejected.

### Generate offline keys

```bash
python deploy/license/generate-keys.py \
  --private-key /secure/offline/beeza-license-private.pem \
  --public-key beeza-license-public.pem
```

The private key must stay offline. Deploy only the public key.

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

Import performs signature, issuer, audience, expiry, activation time, Tenant and Deployment checks. Re-importing the same token re-verifies its signature. The normal status endpoint checks stored expiry and Deployment claims; cryptographic re-verification requires re-importing the token or restarting with `BEEZA_LICENSE_TOKEN` configured.

## Contract entitlements

Phase 14 converts the active Phase 13 subscription into `CONTRACT` entitlement rows and the signed license into `LICENSE` entitlement rows.

Initial plans:

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

Enforcement currently covers operational write paths, Agent registration, Deployment registration and active-work concurrency. Read-only diagnosis and Commercial recovery APIs remain accessible through normal Governance permissions when a license is missing.

## Tenant onboarding

Onboarding steps:

```text
organization
deployment
identity
runtime
governance
backup
verification
go_live
```

Each step records completion, operator note, actor and timestamp. A Tenant reaches `COMPLETED` only after all steps are complete.

```text
GET  /api/commercial/onboarding
POST /api/commercial/onboarding
POST /api/commercial/onboarding/{onboarding_key}/advance
```

The default internal Tenant is seeded as completed so existing local development is not interrupted.

## White label

A Tenant brand profile contains:

- Product and company name
- Logo and favicon URLs
- Primary, accent and background colors
- Custom domain
- Support, privacy and terms URLs
- Locale and outbound email identity

```text
GET /api/commercial/brand
PUT /api/commercial/brand
```

The browser applies the profile to the application title, sidebar identity, logo mark and CSS variables. In enforced mode, editing requires the `white_label` entitlement.

## Deployment activation

Deployment records contain:

- Deployment ID and fingerprint
- Environment and site
- Hostname
- Application version
- Container image digest
- License association
- Heartbeat status and last-seen timestamp

```text
GET  /api/commercial/deployments
POST /api/commercial/deployments
POST /api/commercial/deployments/{deployment_key}/heartbeat
```

A deployment becomes `ACTIVE` only when an active license is associated. The deployment count is limited by the effective contract/license quota.

## Signed releases

`.github/workflows/release.yml` runs for `v*` tags and:

1. Builds the application image.
2. Pushes immutable tags to GHCR.
3. Generates SBOM and provenance attestations.
4. Signs the image digest with Cosign and GitHub OIDC.
5. Verifies the signature in the workflow.
6. Produces `release-manifest.json`, checksum and installer command artifacts.

The runtime starts with release `0.15.0` marked `UNSIGNED`. It becomes `PUBLISHED` only after an operator or release service imports a verified manifest:

```text
POST /api/commercial/releases/publish
```

The endpoint records the image digest, signature reference, SBOM reference, provenance reference, source commit and certificate identity. It does not independently execute Cosign; signature verification must occur in CI and again in the production installer.

## Production installer

```text
deploy/install/install.sh
deploy/install/compose.production.yml
```

The installer:

- Requires Docker Compose v2.
- Requires an image pinned by SHA-256 digest.
- Requires Cosign verification unless explicitly bypassed.
- Creates protected random PostgreSQL, platform and metrics secrets.
- Defaults to license enforcement.
- Uses a read-only application container with `no-new-privileges`.
- Starts PostgreSQL and Redis with durable volumes.
- Waits for `/health/ready` and prints logs on failure.
- Preserves an existing `.env` during upgrades.

Example from a signed release artifact:

```bash
BEEZA_IMAGE=ghcr.io/paddman/beezaoffice:0.15.0@sha256:... \
BEEZA_COSIGN_IDENTITY=https://github.com/paddman/Beezaoffice/.github/workflows/release.yml@refs/tags/v0.15.0 \
BEEZA_LICENSE_PUBLIC_KEY="$(awk '{printf "%s\\n",$0}' beeza-license-public.pem)" \
BEEZA_LICENSE_TOKEN="$(cat customer-a.jwt)" \
sh deploy/install/install.sh
```

Binding defaults to `127.0.0.1:8080`; place an approved TLS reverse proxy or ingress in front of it.

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

License changes, brand changes, Deployment management and release publishing are execution-controlled Governance actions.

## Observability

Phase 14 adds:

```text
beeza_commercial_active_licenses
beeza_commercial_active_deployments
beeza_commercial_completed_onboarding
beeza_commercial_published_releases
```

`/api/health` reports Phase 14, License mode/status, Deployment ID and whether a signed release manifest is registered.

## Production boundary

Phase 14 provides a commercial-control baseline, not a legal billing or DRM guarantee.

- A database administrator can alter local entitlement data; protect PostgreSQL and audit access.
- The private license key must remain offline or inside an approved HSM/KMS signing service.
- `warn` and `development` are not production enforcement modes.
- A release is not signed merely because a manifest row exists. Verify the OCI signature and digest.
- Installer bypass flags are for controlled recovery/testing and should be prohibited by production policy.
- Contract plans and price references require legal, tax and commercial review.
- Custom domains still require DNS, TLS certificates and ingress configuration.
