# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is an operations-first command center where agents receive missions, join mission rooms, assign work, wait for dependencies, hand work off, follow up, request approval, hold structured meetings, record decisions, verify evidence, and report results to humans.

## Current MVP

- Command Center dashboard and live organization map
- Mission queue, collaboration timeline and approval surfaces
- PostgreSQL and Redis state
- Docker Compose deployment
- **Agent Runtime Mesh:** OpenClaw, CherryAgent, Hermes Agent and thClaws
- **Phase 2 runtime control:** status sync, remote result capture, Hermes safe stop and approvals
- **Phase 3 unified event stream:** durable runtime events, server synchronization and mission SSE
- **Phase 4 collaboration bus:**
  - Typed cross-runtime handoffs and work contracts
  - Task dependencies and automatic unblocking
  - Agent/runtime mailbox with delivery state
  - Automatic dispatch to any configured runtime
  - Result return, human review, revision and retry
  - Follow-up watchdog, deadline detection and escalation
- **Phase 5 agent meeting manager:**
  - Structured agenda and role-based participants
  - Turn-based discussion across connected runtimes
  - Bounded rounds to prevent repetitive loops
  - Human decision gate and action-item generation
- **Phase 6 governance and identity:**
  - Tenant, department, human, agent, service and runtime identities
  - Role-based access control with scoped role bindings
  - Clearance checks for public, internal, confidential and restricted data
  - Risk and cost-aware policy rules
  - Second-person approval workflow for high-risk execution
  - Per-identity daily and monthly budgets
  - Emergency runtime execution kill switch
  - SHA-256 hash-chained audit ledger
  - Governance checks at HTTP and internal runtime-dispatch boundaries
- **Phase 7 agent registry and organization graph:**
  - Governed workforce directory designed for 1,000 registered agents
  - Department and manager reporting lines
  - Agent lifecycle, availability and heartbeat state
  - Preferred runtime and model
  - Concurrency, workload and available capacity
  - Reliability and run history
  - Skills, capabilities, allowed tools and data clearance
  - Organization graph, skill matrix and temporary delegation
  - Agent creation, activation, suspension and workload reconciliation

BeezaOffice remains the command and governance plane. Connected runtimes keep their own tools, skills, memory, sessions, sandboxes and local approval policies.

## Quick deploy

```bash
cp .env.example .env
# Set strong PostgreSQL and BeezaOffice credentials and configure only the runtimes in use.
docker compose -f compose.yml up -d --build
```

Open:

- BeezaOffice: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- API docs: `http://localhost:8080/docs`
- Runtime event worker: `http://localhost:8080/api/runtime-event-worker`
- Collaboration worker: `http://localhost:8080/api/collaboration/worker`
- Meeting worker: `http://localhost:8080/api/meeting-worker`
- Governance context: `http://localhost:8080/api/governance/context`
- Agent registry stats: `http://localhost:8080/api/registry/stats`
- Organization graph: `http://localhost:8080/api/registry/organization`

## Core configuration

```env
BEEZA_AUTH_TOKEN=SET_A_LONG_RANDOM_TOKEN

BEEZA_GOVERNANCE_ENFORCED=true
BEEZA_DEFAULT_IDENTITY=human:owner
BEEZA_APPROVAL_TTL_MINUTES=60

BEEZA_RUNTIME_SYNC_ENABLED=true
BEEZA_RUNTIME_SYNC_INTERVAL_SECONDS=5

BEEZA_COLLAB_ENABLED=true
BEEZA_COLLAB_INTERVAL_SECONDS=3
BEEZA_COLLAB_FOLLOW_UP_SECONDS=300
BEEZA_COLLAB_MAX_FOLLOW_UPS=2

BEEZA_MEETING_ENABLED=true
BEEZA_MEETING_INTERVAL_SECONDS=3
BEEZA_MEETING_TURN_TIMEOUT_SECONDS=900
```

## Governance request headers

Governed browser and API mutations can include:

```text
Authorization: Bearer <BEEZA_AUTH_TOKEN>
X-Beeza-Identity: human:owner
X-Beeza-Risk-Level: NORMAL
X-Beeza-Data-Classification: INTERNAL
X-Beeza-Estimated-Cost-USD: 0
X-Beeza-Approval-Key: APR-...        # only when an approved request is required
```

The Command Center Governance panel sets these headers automatically.

## Seeded identities

| Identity | Purpose |
|---|---|
| `human:owner` | Platform owner and emergency control authority |
| `human:executive` | Independent second approver |
| `human:operator` | Operational mission and runtime control |
| `human:auditor` | Read-only audit and governance review |
| `agent:Beeza Commander` | Agent manager and mission coordinator |
| `agent:Beeza Moderator` | Structured meeting moderator |
| `service:runtime` | Internal runtime dispatch service |
| `service:collaboration` | Collaboration scheduler |
| `service:meeting` | Meeting scheduler |
| `runtime:openclaw`, `runtime:cherryagent`, `runtime:hermes`, `runtime:thclaws` | Runtime principals |

The 12 founding BeezaOffice agents are also seeded as Governance identities and Phase 7 registry profiles.

## Governance behavior

### RBAC

Every mutating API route is mapped to a permission such as:

```text
mission:create
runtime:dispatch
runtime:stop
handoff:create
task:control
task:review
meeting:create
meeting:start
meeting:decide
registry:write
registry:heartbeat
registry:delegate
approval:decide
governance:kill-switch
```

Roles grant exact or wildcard permissions such as `runtime:*`.

### High-risk approval

A `HIGH` or `CRITICAL` runtime dispatch, task control action or meeting decision may return HTTP `428` with a pending approval request.

```text
Requester performs high-risk action
  → BeezaOffice returns APR-...
  → switch to human:executive
  → approve request
  → switch back to requester
  → arm approval key
  → retry original action
  → approval becomes USED
```

The requester cannot approve its own request.

### Kill switch

Disabling runtime execution blocks:

- Runtime dispatch
- Runtime stop and approval controls
- Cross-runtime handoff execution
- Task control actions
- Meeting start, control and decision execution
- Internal meeting and collaboration worker dispatches

Read-only monitoring, registry search and governance recovery remain available.

### Budget enforcement

An estimated cost supplied through `X-Beeza-Estimated-Cost-USD` is checked against the current identity's daily and monthly limits. Successful governed mutations can create budget reservations, while actual charges can be recorded through the budget API.

### Audit chain

Every governed mutation records:

- Identity and permission
- Method, path and mission resource
- Outcome and response status
- Risk, classification and estimated cost
- Source address and request ID
- Previous hash and current SHA-256 record hash

The audit verification endpoint recomputes the chain and reports the first broken record.

## Agent Registry

Each Phase 7 registry profile carries:

```text
Agent key and Governance identity
Display name and role
Department and manager
Status and availability
Preferred runtime and model
Maximum concurrency and live workload
Reliability and run counters
Skills and capabilities
Allowed tools and data clearance
Version and owner
Heartbeat and profile metadata
```

Registry status:

```text
ACTIVE
SUSPENDED
RETIRED
```

Availability:

```text
AVAILABLE
BUSY
WAITING
OFFLINE
MAINTENANCE
```

The registry does not start one process per profile. It records the logical workforce and capacity while the runtime pool executes only active work.

### Registry permissions

```text
registry:read
registry:write
registry:heartbeat
registry:delegate
```

Agent heartbeat is limited to the agent's own identity unless the caller also has `registry:write`.

### Registry API

```text
GET   /api/registry/stats
GET   /api/registry/agents
POST  /api/registry/agents
GET   /api/registry/agents/{agent_key}
PATCH /api/registry/agents/{agent_key}
POST  /api/registry/agents/{agent_key}/heartbeat
GET   /api/registry/organization
GET   /api/registry/skills
GET   /api/registry/delegations
POST  /api/registry/delegations
POST  /api/registry/reconcile
```

Workload reconciliation maps active Collaboration Bus tasks onto matching agent identities and updates utilization and availability.

## Governance API

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
POST /api/governance/approvals/{approval}/decision
GET  /api/governance/controls
POST /api/governance/kill-switch
GET  /api/governance/budget
POST /api/governance/budget/charge
GET  /api/governance/audit
GET  /api/governance/audit/verify
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

See `docs/RUNTIME-INTEGRATIONS.md` for adapter-specific setup and security boundaries.

## Architecture

```text
Agent Registry and Organization Graph
        ├─ identity, role, manager and department
        ├─ skill and capability matrix
        ├─ runtime preference
        ├─ capacity and reliability
        └─ delegation
                ↓
Human / Agent / Service Identity
        ↓ RBAC + clearance + budget + policy
Governance Middleware
        ├─ approval workflow
        ├─ emergency kill switch
        ├─ budget ledger
        └─ hash-chained audit
        ↓
Mission / Meeting / Collaboration APIs
        ↓
Governed Runtime Dispatch Boundary
        ├─ OpenClaw
        ├─ CherryAgent
        ├─ Hermes Agent
        └─ thClaws
        ↓
Runtime Events → Evidence → Review → Decision
```

## Product direction

1. Workforce Kernel
2. Durable Mission Runtime
3. Collaboration Protocol
4. Structured Meetings and Decisions
5. Governance and Identity
6. Agent Registry and Organization Graph
7. Scheduler and Runtime Pool
8. Evaluation, Verification and Replay
9. SOP Builder
10. Enterprise Deployment
11. Scale to 1,000 registered agents

See `docs/PHASE-6-GOVERNANCE.md` and `docs/PHASE-7-AGENT-REGISTRY.md` for the current control-plane architecture.
