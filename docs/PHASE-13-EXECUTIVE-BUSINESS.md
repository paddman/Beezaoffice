# Phase 13 — Executive & Business Layer

Phase 13 converts verified agent work into business evidence. It adds outcome records, executive snapshots, department scorecards, agent economics, SLA measurement, billing meters, subscription plans and installable industry-pack manifests.

## Business evidence flow

```text
Mission
  ↓
Collaboration Task
  ↓
Runtime Dispatch
  ↓
Evaluation Run
  ↓ PASS / WARN / FAIL
Business Outcome
  ├─ quality and evidence
  ├─ elapsed time and SLA
  ├─ baseline versus actual cost
  ├─ hours saved
  ├─ attributed revenue value
  └─ department and agent attribution
  ↓
Executive Dashboard / Snapshot / Billing / Marketplace
```

Only evaluated work is synchronized automatically. A task without an Evaluation Run is not treated as a verified business outcome.

## Outcome records

`business_outcomes` stores one current outcome per tenant and Collaboration Task.

Important fields:

- Tenant, Mission and Task keys
- Department and Agent identity
- `VERIFIED`, `REVIEW`, `FAILED` or `VOID`
- `ESTIMATED`, `MANUAL` or `IMPORTED` source mode
- Evaluation quality score and evidence count
- Baseline and actual duration
- Hours saved
- Baseline and actual cost
- Cost saved and revenue value
- SLA target and compliance
- Evaluation result hash
- Measurement assumptions and metadata

### Automatic synchronization

The business worker scans the latest Evaluation Run for each tenant task.

```text
PASS  → VERIFIED
WARN  → REVIEW
FAIL  → FAILED
ERROR → FAILED
```

Automatic records use the following estimation order:

1. Explicit values in Collaboration Task context
2. Deadline-derived SLA when available
3. Priority-based baseline and SLA defaults
4. Actual elapsed time multiplied by the configured estimation factor

Mission budget charges are attributed directly when a ledger entry references the Task. Unassigned Mission charges are divided among evaluated Tasks in that Mission.

Estimated values are marked with `source_mode=ESTIMATED` and carry their assumptions. A `MANUAL` or `IMPORTED` outcome is never overwritten by the automatic worker.

### Manual outcome entry

```text
POST /api/business/outcomes
```

Manual entry is intended for confirmed finance, operations or departmental data. It can replace estimated time, cost and revenue attribution for a Task.

## Executive metrics

The Executive dashboard calculates:

- Measured outcomes
- Verified, review and failed outcomes
- Verification rate
- Average evaluation quality
- Evidence count
- Hours saved
- Baseline and actual cost
- Cost saved
- Attributed revenue value
- Total value created
- Value-to-cost ratio
- SLA compliance
- Estimated versus manually verified records
- Mission count

`value_created_usd` is:

```text
cost_saved_usd + revenue_value_usd
```

`roi_ratio` is:

```text
value_created_usd / actual_cost_usd
```

The ratio is omitted when actual cost is zero.

## Department scorecards

Outcomes are grouped by governed Department. Each scorecard includes:

- Active agent count
- Outcome and verification count
- Average quality
- Hours and cost saved
- Value created
- SLA compliance
- Risk tier

Departments without measured outcomes are not ranked yet.

## Agent economics

Agent economics groups outcomes by target identity and combines them with Registry and Budget data:

- Verified outcomes
- Quality score
- Hours saved
- Actual governed cost
- Value created
- Value-to-cost ratio
- SLA compliance
- Registry reliability and total runs

This is an operational accountability view, not an employee compensation or performance-review system.

## Executive snapshots

```text
POST /api/business/snapshots
GET  /api/business/snapshots
```

A snapshot preserves:

- Period start and end
- Executive metrics
- Department scorecards
- Agent economics
- SHA-256 integrity hash
- Creating identity and timestamp

Snapshots are append-only records. They allow board packs and reports to reference a fixed scorecard rather than a continuously changing dashboard.

## Usage metering and billing

Phase 13 maintains daily tenant meters in `business_usage_daily`.

Initial meters:

```text
api_requests
runtime_dispatches
external_tasks
sop_runs
backup_runs
verified_outcomes
pack_installs
```

HTTP requests are metered after successful processing. Outcome synchronization and industry-pack installation are metered transactionally with their business records.

Seeded plans:

- Team
- Enterprise
- Sovereign

A plan contains:

- Monthly price
- Included units by meter
- Overage rate by meter
- Feature list
- Deployment mode

A Tenant subscription can override the monthly contract value.

```text
GET  /api/business/plans
GET  /api/business/billing
GET  /api/business/usage
POST /api/business/subscription
```

The billing endpoint produces an estimate. It does not calculate tax, discounts, support retainers, infrastructure pass-through or legally binding invoices.

## Industry packs

Phase 13 seeds four vertical packs:

- Government Document Operations
- IDC & SOC Incident Command
- AI CFO Office
- Customer Support Operations

Each pack contains:

- Industry and version
- Capability manifest
- Expected SOP templates
- Required connectors
- Governance and verification requirements
- Commercial reference price

```text
GET  /api/business/industry-packs
POST /api/business/industry-packs/{pack_key}/install
```

Installation creates a tenant-owned governed manifest. It does not silently create production credentials or activate external connectors. Each connector and SOP implementation must still be configured, reviewed and verified.

## Worker and locking

The business worker runs every 60 seconds by default:

```env
BEEZA_BUSINESS_ENABLED=true
BEEZA_BUSINESS_INTERVAL_SECONDS=60
BEEZA_DEFAULT_LABOR_RATE_USD=30
```

Each tenant synchronization uses a Redis `NX` lock. Multiple web replicas can run the worker without intentionally processing the same tenant at the same time.

Manual synchronization:

```text
POST /api/business/sync
```

## Governance permissions

```text
business:read
business:sync
business:outcome:write
business:snapshot
business:billing:manage
business:pack:install
```

Billing changes and industry-pack installation are execution-controlled Governance actions.

## API

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

## Observability

Phase 13 extends `/metrics` with:

```text
beeza_business_outcomes_total
beeza_business_verified_outcomes
beeza_business_hours_saved
beeza_business_value_created_usd
beeza_business_sla_compliance_ratio
beeza_business_installed_packs
beeza_business_active_subscriptions
```

`/api/health` reports Phase 13, worker state, measured outcomes and published industry packs.

## Data-quality boundary

Business metrics are only as reliable as their sources.

- Automatically calculated time and cost are estimates unless overridden.
- Revenue attribution requires explicit business input.
- A high Evaluation score proves output quality against configured policy; it does not independently prove financial value.
- SLA compliance is meaningful only when deadlines or SLA targets are configured correctly.
- Billing output is an operational estimate, not an invoice.
- Industry packs are manifests until connectors and SOPs are implemented and verified.

Executive reports should distinguish `ESTIMATED`, `MANUAL` and `IMPORTED` outcomes.
