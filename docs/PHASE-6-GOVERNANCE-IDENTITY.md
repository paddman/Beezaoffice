# Phase 6 — Governance and Identity

Phase 6 turns BeezaOffice from an orchestration console into a governed AI workforce control plane. Every human, agent, background service and external runtime now acts through a registered identity with roles, clearance, policy, budget and audit evidence.

## Control flow

```text
Request or internal dispatch
        ↓
Resolve identity
        ↓
Validate role permission
        ↓
Check execution kill switch
        ↓
Check data clearance
        ↓
Check daily and monthly budget
        ↓
Evaluate policy rules
        ├─ ALLOW
        ├─ DENY
        └─ APPROVAL REQUIRED
        ↓
Execute operation
        ↓
Record budget and hash-chained audit
```

Governance runs at two boundaries:

1. HTTP middleware for user and API mutations
2. Shared runtime-dispatch wrapper used by direct dispatch, Collaboration Bus and Meeting Manager workers

This means disabling execution also stops background workers from starting new runtime work.

## Data model

### Tenants and departments

`governance_tenants` and `governance_departments` establish the organization boundary and chain of responsibility. Departments support parent relationships and risk tiers.

### Identities

`governance_identities` represents:

- `HUMAN`
- `AGENT`
- `SERVICE`
- `RUNTIME`

Each identity includes tenant, department, lifecycle status, data clearance, daily budget, monthly budget and extensible attributes.

Identity lifecycle states:

```text
ACTIVE
SUSPENDED
REVOKED
```

A suspended or revoked identity cannot perform governed mutations.

### Roles and bindings

`governance_roles` stores permission patterns. `governance_role_bindings` assigns a role to an identity at one of these scopes:

```text
GLOBAL
TENANT
DEPARTMENT
MISSION
```

The initial release evaluates global, tenant, department and exact mission bindings. Seeded roles are:

- Owner
- Executive
- Manager
- Operator
- Auditor
- Agent
- Service
- Runtime

Permissions support wildcards, for example:

```text
runtime:*
meeting:*
approval:*
```

## Route permissions

Mutating routes are converted into typed permissions before the endpoint executes.

| Operation | Permission |
|---|---|
| Create mission | `mission:create` |
| Probe runtime | `runtime:probe` |
| Dispatch runtime work | `runtime:dispatch` |
| Synchronize run | `runtime:sync` |
| Stop remote run | `runtime:stop` |
| Decide runtime tool approval | `runtime:approval` |
| Create handoff | `handoff:create` |
| Control collaboration task | `task:control` |
| Review collaboration task | `task:review` |
| Create meeting | `meeting:create` |
| Start meeting | `meeting:start` |
| Advance or cancel meeting | `meeting:control` |
| Record meeting decision | `meeting:decide` |
| Toggle kill switch | `governance:kill-switch` |

Unknown mutating API routes require `api:write` rather than being implicitly trusted.

## Data clearance

Clearance levels are ordered:

```text
PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED
```

The request header `X-Beeza-Data-Classification` declares the highest data classification involved in an operation. The acting identity must have equal or greater clearance.

Example:

```text
Identity clearance: INTERNAL
Requested data: CONFIDENTIAL
Result: DENIED
```

## Policy rules

`governance_policy_rules` adds conditional rules after RBAC. Each rule contains:

- Action pattern
- Effect: `ALLOW`, `DENY` or `APPROVAL`
- Applicable risk levels
- Minimum clearance
- Optional cost threshold
- Priority
- Additional JSON conditions

Seeded policies require approval for:

- High or critical runtime dispatch
- Critical meeting decisions
- Estimated cost above USD 100

RBAC permission is still required. An `ALLOW` policy does not grant a missing role permission.

## Approval workflow

High-risk work can return HTTP `428 Precondition Required` with a pending approval request.

```text
Requester
  → attempts high-risk action
  → receives APR-...

Independent approver
  → reviews request
  → APPROVED or DENIED

Requester
  → supplies X-Beeza-Approval-Key
  → retries matching action
  → successful use changes approval to USED
```

Approval states:

```text
PENDING
APPROVED
DENIED
EXPIRED
USED
```

The requester cannot approve its own request. The default deployment seeds `human:executive` as a separate approver.

Approval matching requires:

- Same requester identity
- Same action permission
- Approved status
- Unexpired request

## Emergency kill switch

`governance_system_controls` stores `runtime_execution_enabled`.

When disabled, BeezaOffice blocks new execution actions while preserving read-only access, audit review and recovery controls.

Blocked actions include:

- Runtime dispatch
- Runtime stop and remote approvals
- Handoff execution
- Collaboration task control
- Meeting start and control
- Meeting decisions
- Internal collaboration and meeting worker dispatches

The kill switch does not terminate an already running remote process. It prevents BeezaOffice from starting or controlling new execution. Remote cancellation propagation remains a later runtime-control enhancement.

## Budget governance

Each identity has daily and monthly USD limits. The optional request header below supplies an estimated cost:

```text
X-Beeza-Estimated-Cost-USD: 12.50
```

Before execution, BeezaOffice calculates current daily and monthly ledger totals. The request is denied when the estimate would exceed either limit.

Successful governed operations can create `RESERVE` entries. Actual runtime usage can be posted as `CHARGE` entries through the budget API.

Ledger entry types:

```text
RESERVE
CHARGE
RELEASE
ADJUST
```

## Audit ledger

`governance_audit_records` stores every governed mutation and internal runtime dispatch.

Each record includes:

- Request ID
- Identity
- Permission/action
- Method and path
- Mission/resource
- Outcome and status code
- Risk and classification context
- Estimated cost
- Source IP and user agent
- Previous record hash
- Current record hash

Record hashes are computed from a canonical JSON representation using SHA-256.

```text
GENESIS
   ↓
AUD-1 hash
   ↓ previous_hash
AUD-2 hash
   ↓ previous_hash
AUD-3 hash
```

The verification endpoint recomputes each hash and reports the first broken record.

PostgreSQL advisory locking serializes audit-chain append operations so concurrent requests do not produce multiple heads.

## Governance headers

```text
Authorization: Bearer <token>
X-Beeza-Identity: human:owner
X-Beeza-Risk-Level: NORMAL
X-Beeza-Data-Classification: INTERNAL
X-Beeza-Estimated-Cost-USD: 0
X-Beeza-Approval-Key: APR-...
X-Request-ID: optional-caller-request-id
```

The Command Center Governance panel stores the selected identity and operating context locally and sends these headers through `operatorApi`.

## Seeded identities

The default installation creates:

- `human:owner`
- `human:executive`
- `human:operator`
- `human:auditor`
- `agent:Beeza Commander`
- `agent:Beeza Moderator`
- `service:runtime`
- `service:collaboration`
- `service:meeting`
- Runtime principals for all four adapters
- Governance identities for the 12 founding agents

These are bootstrap identities for the MVP. Production SSO and external identity-provider mapping are not part of this phase.

## API

```text
GET  /api/governance/context
GET  /api/governance/identities
POST /api/governance/identities
GET  /api/governance/roles
POST /api/governance/bindings
GET  /api/governance/policies
POST /api/governance/policies
GET  /api/governance/approvals
POST /api/governance/approvals
POST /api/governance/approvals/{approval_key}/decision
GET  /api/governance/controls
POST /api/governance/kill-switch
GET  /api/governance/budget
POST /api/governance/budget/charge
GET  /api/governance/audit
GET  /api/governance/audit/verify
```

## Configuration

```env
BEEZA_GOVERNANCE_ENFORCED=true
BEEZA_DEFAULT_IDENTITY=human:owner
BEEZA_APPROVAL_TTL_MINUTES=60
```

Disabling governance enforcement is intended only for isolated development. Production should keep it enabled.

## Operational checks

```bash
curl -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
     -H "X-Beeza-Identity: human:owner" \
     http://localhost:8080/api/governance/context

curl -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
     -H "X-Beeza-Identity: human:auditor" \
     http://localhost:8080/api/governance/audit/verify
```

Disable execution:

```bash
curl -X POST \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  -H "Content-Type: application/json" \
  -d '{"execution_enabled":false,"reason":"Emergency operational stop"}' \
  http://localhost:8080/api/governance/kill-switch
```

## Current boundary

Phase 6 does not yet provide:

- OIDC, SAML or Active Directory authentication
- Cryptographic per-identity access tokens
- External Vault/KMS secret references
- Row-level tenant isolation enforced in every existing table
- Automatic usage reconciliation from every runtime
- Signed policy bundles
- Automated voting for consensus or majority meetings
- Immediate remote-process termination from the kill switch

Those belong to the enterprise identity, secrets and deployment phases. Phase 6 establishes the durable governance model and enforcement boundaries needed before scaling the Agent Registry and Scheduler.
