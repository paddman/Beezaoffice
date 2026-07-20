# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is an operations-first command center where governed agents receive missions, collaborate across runtimes, hold structured meetings, record decisions, route work intelligently, preserve evidence and report verified outcomes to humans.

## Current system

- Command Center dashboard and digital organization map
- PostgreSQL durable state and Redis worker coordination
- Docker Compose deployment
- Runtime Mesh: OpenClaw, CherryAgent, Hermes Agent and thClaws
- Mission queue, war room, event feed and approval surfaces

### Phase 2 — Runtime control

- Runtime dispatch and status synchronization
- Remote output capture
- Safe stop and Hermes approval controls

### Phase 3 — Unified event stream

- Durable runtime events
- Server-side synchronization worker
- Mission-scoped Server-Sent Events
- CherryAgent task, handoff, evidence and log capture
- Hermes status, approval, result and usage capture

### Phase 4 — Collaboration Bus

- Typed cross-runtime handoffs and work contracts
- Task dependencies and automatic unblocking
- Agent/runtime mailbox
- Result return, human review, revision and retry
- Follow-up watchdog, deadline detection and escalation

### Phase 5 — Agent Meeting Manager

- Structured agendas and participant roles
- Turn-based discussion across connected runtimes
- Bounded rounds that prevent repetitive loops
- Human decision gate
- Accepted decisions converted into Collaboration Bus action items

### Phase 6 — Governance and Identity

- Tenant, department, human, agent, service and runtime identities
- Scoped RBAC
- Data-clearance enforcement
- Risk and cost-aware policies
- Independent second-person approval
- Per-identity budgets
- Emergency execution kill switch
- SHA-256 hash-chained audit ledger
- Enforcement at both HTTP and internal runtime-dispatch boundaries

### Phase 7 — Agent Registry and Organization Graph

- Governed directory designed for 1,000 registered agents
- Department and manager reporting lines
- Lifecycle, availability and heartbeat state
- Preferred runtime and model
- Concurrency, workload and available capacity
- Reliability and run history
- Skills, capabilities, allowed tools and clearance
- Organization graph, skill matrix and temporary delegation

### Phase 8 — Scheduler and Intelligent Router

- Smart tasks that do not require a named agent or runtime
- Hard filtering by lifecycle, availability, clearance, capacity and cost
- Weighted scoring by skill, reliability, capacity, runtime health, latency, cost, deadline and affinity
- Runtime pool capacity for OpenClaw, CherryAgent, Hermes and thClaws
- Durable explainable routing decisions
- Route simulation before execution
- Backpressure and retry when no route is available
- Automatic failover that excludes a failed agent/runtime
- Safe rerouting that refuses to duplicate active remote execution

BeezaOffice remains the command and governance plane. Connected runtimes keep their own tools, skills, memory, sessions, sandboxes and local approval policies.

## Quick deploy

```bash
cp .env.example .env
# Set strong PostgreSQL and BeezaOffice credentials.
# Configure only the runtimes that will be used.
docker compose -f compose.yml up -d --build
```

Open:

- Command Center: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- API docs: `http://localhost:8080/docs`
- Runtime worker: `http://localhost:8080/api/runtime-event-worker`
- Collaboration worker: `http://localhost:8080/api/collaboration/worker`
- Meeting worker: `http://localhost:8080/api/meeting-worker`
- Governance: `http://localhost:8080/api/governance/context`
- Agent Registry: `http://localhost:8080/api/registry/stats`
- Scheduler: `http://localhost:8080/api/scheduler/status`
- Runtime pool: `http://localhost:8080/api/scheduler/runtime-pool`

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

BEEZA_SCHEDULER_ENABLED=true
BEEZA_SCHEDULER_INTERVAL_SECONDS=3
BEEZA_SCHEDULER_BATCH_SIZE=100
BEEZA_SCHEDULER_FAILOVER_ATTEMPTS=3
```

## Governance headers

```text
Authorization: Bearer <BEEZA_AUTH_TOKEN>
X-Beeza-Identity: human:owner
X-Beeza-Risk-Level: NORMAL
X-Beeza-Data-Classification: INTERNAL
X-Beeza-Estimated-Cost-USD: 0
X-Beeza-Approval-Key: APR-...        # when approved execution is required
```

The Command Center sets these headers for governed browser operations.

## Seeded identities

| Identity | Purpose |
|---|---|
| `human:owner` | Platform owner and emergency authority |
| `human:executive` | Independent approver |
| `human:operator` | Mission and runtime operator |
| `human:auditor` | Read-only governance reviewer |
| `agent:Beeza Commander` | Mission coordinator |
| `agent:Beeza Moderator` | Meeting moderator |
| `service:runtime` | Runtime service principal |
| `service:collaboration` | Collaboration scheduler |
| `service:meeting` | Meeting scheduler |
| `runtime:openclaw`, `runtime:cherryagent`, `runtime:hermes`, `runtime:thclaws` | Runtime principals |

The 12 founding agents are also seeded as Governance identities and Phase 7 Registry profiles.

## Intelligent routing

A Phase 8 smart task declares requirements rather than a fixed executor:

```text
Objective and priority
Required skills, capabilities and tools
Required data clearance
Preferred department and runtime
Estimated tokens and maximum cost
Strict matching or overflow policy
Deadline
Expected outputs and acceptance criteria
```

The task begins as:

```text
agent:auto
runtime: auto
```

The balanced policy applies hard eligibility checks and then scores candidates with these default weights:

| Component | Weight |
|---|---:|
| Skill/capability/tool coverage | 28% |
| Reliability | 20% |
| Agent capacity | 18% |
| Runtime health and latency | 14% |
| Estimated cost | 10% |
| Deadline response | 6% |
| Affinity | 4% |

Every attempt stores the full ranked candidate evidence in `routing_decisions`.

### Scheduler permissions

```text
scheduler:read
scheduler:route
scheduler:policy:write
```

### Scheduler API

```text
GET   /api/scheduler/status
POST  /api/scheduler/tick
GET   /api/scheduler/runtime-pool
GET   /api/scheduler/policies
PATCH /api/scheduler/policies/{policy_key}
GET   /api/scheduler/decisions
POST  /api/scheduler/simulate
POST  /api/missions/{mission_key}/routed-tasks
POST  /api/scheduler/tasks/{task_key}/route
```

## Agent Registry API

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

Logical agents are not individual permanent processes. The Registry records the workforce, while active runtime slots execute only current work.

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

## Architecture

```text
Smart Task
    ↓ requirements
Agent Registry + Organization Graph
    ↓ eligibility and scoring
Scheduler Policy + Runtime Pool
    ↓ explainable routing decision
Governance Middleware
    ↓ RBAC + clearance + budget + policy + approval
Collaboration Bus
    ↓ governed dispatch
OpenClaw / CherryAgent / Hermes / thClaws
    ↓ events, evidence and result
Review / Meeting / Decision / Follow-up
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

Architecture documents:

- `docs/PHASE-6-GOVERNANCE.md`
- `docs/PHASE-7-AGENT-REGISTRY.md`
- `docs/PHASE-8-SCHEDULER-ROUTER.md`
- `docs/RUNTIME-INTEGRATIONS.md`
