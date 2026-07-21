# Phase 14.1 — Release Candidate & Pilot Gate

Phase 14.1 does not add another product layer. It converts the Phase 1–14 codebase into a repeatable release-candidate gate with versioned migrations, tenant-isolation checks and a destructive restore drill.

## Gate flow

```text
Build container
→ Start PostgreSQL and Redis
→ Alembic upgrade head
→ Start with BEEZA_SCHEMA_STRICT=true
→ Create two Tenants and two Missions
→ Prove cross-Tenant reads return 404
→ Create PostgreSQL recovery point
→ Destroy the database
→ Restore the database
→ Re-run schema and Tenant-isolation verification
```

The automated workflow is `.github/workflows/pilot-gate.yml`.

## Versioned schema

Alembic files:

```text
app/alembic.ini
app/migrations/env.py
app/migrations/versions/20260721_0001_phase14_baseline.py
app/schema_service.py
app/phase14_schema.py
```

The first revision is a non-destructive adoption baseline. It creates missing Phase 1–14 tables and safely migrates the Commercial entitlement uniqueness constraint to:

```text
Tenant + Feature + Source
```

Its downgrade deliberately does not drop customer tables. Future schema changes must use explicit reversible Alembic revisions.

### Local migration

```bash
cd app
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
```

### Schema readiness

```text
GET /health/ready
GET /api/system/schema
```

Production uses:

```env
BEEZA_SCHEMA_STRICT=true
```

When strict mode is enabled, readiness returns HTTP `503` and application startup fails when the database is not at the expected revision.

## Production installer behavior

`deploy/install/install.sh` now performs:

1. Image digest and Cosign verification.
2. PostgreSQL and Redis startup.
3. Pre-migration PostgreSQL backup when an existing schema is detected.
4. `alembic upgrade head`.
5. Runtime revision verification.
6. Migration-strict application startup.
7. Deployment fingerprint and image-digest registration.

Pre-migration dumps are stored under:

```text
/opt/beezaoffice/migration-backups
```

## Kubernetes migration

Run the migration Job before updating the Deployment:

```bash
kubectl apply -f deploy/k8s/migrate-job.yaml
kubectl -n beezaoffice wait \
  --for=condition=complete \
  job/beezaoffice-schema-migrate \
  --timeout=10m
```

The image must be replaced with the same signed digest that will run in the application Deployment.

## Pilot environment

```bash
docker build -t beezaoffice:pilot ./app
docker compose -f deploy/pilot/compose.yml up -d postgres redis

docker compose -f deploy/pilot/compose.yml run --rm beezaoffice \
  alembic -c alembic.ini upgrade head

docker compose -f deploy/pilot/compose.yml up -d beezaoffice
python tests/pilot_gate.py --mode prepare
```

## Tenant-isolation assertions

The pilot test creates:

```text
tenant:beeza  → Mission A
tenant:pilot-b → Mission B
```

It verifies:

- Tenant A lists Mission A but not Mission B.
- Tenant B lists Mission B but not Mission A.
- Tenant A reading Mission B returns `404`.
- Tenant B reading Mission A returns `404`.
- Response Tenant headers match the authorized Tenant.
- The Alembic current revision equals the repository head revision.

## Restore drill

The GitHub workflow performs a destructive PostgreSQL restore test:

```text
pg_dump custom archive
→ stop BeezaOffice
→ drop beezaoffice database
→ recreate database
→ pg_restore
→ restart BeezaOffice
→ verify both Missions and Tenant isolation
```

The drill demonstrates database recoverability only. Production still needs Redis-state policy, object-store evidence restore, encryption-key recovery and a timed DR exercise.

## Pull-request release gate

A release-candidate PR must have both workflows green:

```text
CI
Pilot Gate
```

Only after both succeed should a release-candidate tag be created:

```bash
git tag v0.15.0-rc1
git push origin v0.15.0-rc1
```

The signed-release workflow then produces the immutable image digest, signature, SBOM, provenance and release manifest.

## Current limits

- The pilot uses a development license; signed customer-license acceptance is covered by the cryptographic self-test, not this HTTP drill.
- The restore test covers PostgreSQL. Object storage and external Runtime systems are not destroyed or restored.
- Runtime E2E requires a real configured OpenClaw, CherryAgent, Hermes or thClaws endpoint.
- Load, failover and penetration testing remain separate pre-production gates.
