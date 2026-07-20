# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 governed AI agents.

BeezaOffice is an operations-first command center where agents receive missions, collaborate across runtimes, hold structured meetings, route work intelligently, preserve evidence, verify results, turn successful work into versioned SOPs and report accountable outcomes to humans.

## Current system

- FastAPI control plane
- PostgreSQL durable state
- Redis worker coordination and locks
- Docker Compose deployment
- OpenClaw, CherryAgent, Hermes Agent and thClaws Runtime Mesh
- Mission queue, War Room, live event feed and approval surfaces

### Phase 2 — Runtime Control

- Runtime dispatch and status synchronization
- Remote output capture
- Hermes safe stop and approvals

### Phase 3 — Unified Event Stream

- Durable runtime events
- Server-side synchronization
- Mission-scoped SSE
- CherryAgent task, handoff, evidence and log capture
- Hermes status, approval, result and usage capture

### Phase 4 — Collaboration Bus

- Typed cross-runtime handoffs and work contracts
- Task dependencies and automatic unblocking
- Agent/runtime mailbox
- Result return, human review, revision and retry
- Follow-up watchdog, deadlines and escalation

### Phase 5 — Agent Meeting Manager

- Structured agendas and participant roles
- Turn-based discussion across runtimes
- Bounded rounds
- Human decision gate
- Accepted decisions converted into Collaboration Bus action items

### Phase 6 — Governance and Identity

- Human, agent, service and runtime identities
- Scoped RBAC
- Data-clearance enforcement
- Risk and cost-aware policies
- Independent second-person approval
- Per-identity budgets
- Emergency execution kill switch
- SHA-256 hash-chained audit ledger
- Enforcement at HTTP and internal runtime-dispatch boundaries

### Phase 7 — Agent Registry and Organization Graph

- Governed directory designed for 1,000 logical agents
- Department and manager reporting lines
- Lifecycle, availability and heartbeat
- Preferred runtime and model
- Concurrency, workload and capacity
- Reliability and run history
- Skills, capabilities, tools and clearance
- Organization graph, skill matrix and delegation

### Phase 8 — Scheduler and Intelligent Router

- Smart tasks without a named agent or runtime
- Eligibility filtering by lifecycle, clearance, capacity and cost
- Weighted routing by skill, reliability, capacity, runtime health, latency, cost, deadline and affinity
- Runtime-pool capacity
- Explainable routing decisions
- Route simulation
- Backpressure, retry and automatic failover
- Safe rerouting that refuses duplicate active execution

### Phase 9 — Evaluation, Verification and Replay

- Deterministic evidence-quality evaluation
- Acceptance-criteria coverage
- Supporting evidence and runtime provenance
- Completeness, consistency, reproducibility and risk scores
- `PASS`, `WARN` and `FAIL`
- Failed auto-completions reopened for review
- Controlled `SAME`, `REROUTE` and `FAILOVER` replay
- Original/replay score comparison
- Verified quality blended into Registry reliability

### Phase 10 — SOP Builder and Workflow Templates

- Draft, published and deprecated SOP lifecycle
- Immutable version definitions with canonical SHA-256 checksum
- Dependency-graph validation and cycle detection
- JSON input schemas and bounded variable rendering
- Task and human-approval nodes
- Automatic Scheduler and Collaboration Bus integration
- Phase 9 verification gate before a node is trusted
- Reverse-order compensation tasks when later work fails
- Governed run, approval, publication and cancellation permissions
- Derive a draft from `PASS`-verified mission tasks
- Seeded Verified Incident Response and Daily Operations Brief procedures

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
- Evaluator: `http://localhost:8080/api/evaluation/status`
- SOP engine: `http://localhost:8080/api/sop/status`

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

BEEZA_EVALUATOR_ENABLED=true
BEEZA_EVALUATOR_INTERVAL_SECONDS=10
BEEZA_EVALUATOR_BATCH_SIZE=100

BEEZA_SOP_ENABLED=true
BEEZA_SOP_INTERVAL_SECONDS=3
BEEZA_SOP_BATCH_SIZE=100
```

Evaluator and SOP settings have safe defaults in code. Existing `.env` files do not need to add them immediately.

## Governance headers

```text
Authorization: Bearer <BEEZA_AUTH_TOKEN>
X-Beeza-Identity: human:owner
X-Beeza-Risk-Level: NORMAL
X-Beeza-Data-Classification: INTERNAL
X-Beeza-Estimated-Cost-USD: 0
X-Beeza-Approval-Key: APR-...
```

The Command Center sets these headers for governed browser operations.

## Seeded service identities

| Identity | Purpose |
|---|---|
| `service:runtime` | Runtime dispatch |
| `service:collaboration` | Collaboration scheduler |
| `service:meeting` | Structured meeting worker |
| `service:scheduler` | Intelligent agent/runtime router |
| `service:evaluator` | Evidence evaluation and replay comparison |
| `service:sop` | SOP graph execution, approvals and rollback orchestration |

## SOP execution

A published procedure creates a new mission and node-run ledger:

```text
Published SOP
    ↓ inputs + checksum
SOP Run / Mission
    ↓
TASK nodes → Scheduler → Agent → Runtime
APPROVAL nodes → Human gate
    ↓
Evaluation PASS / WARN / FAIL
    ↓
Next ready nodes or rollback
```

### Template lifecycle

```text
DRAFT → PUBLISHED → DEPRECATED
```

Publishing a new version deprecates the previous active version. Existing runs retain their original version and checksum.

### Verification gate

```text
Runtime completed, no evaluation → keep waiting
PASS                             → complete node
WARN                             → human approval
FAIL                             → fail run and start rollback when defined
```

### Rollback

Completed nodes with rollback definitions are compensated in reverse dependency order. A successful compensation sequence leaves the original run `FAILED`; it proves recovery, not completion of the intended procedure.

### Derive from verified work

```text
Mission
  → latest PASS evaluation per Collaboration Task
  → preserve dependency graph and execution constraints
  → create DRAFT SOP
  → human review
  → publish
```

## SOP API

```text
GET  /api/sop/status
POST /api/sop/tick

GET  /api/sop/templates
POST /api/sop/templates
GET  /api/sop/templates/{template_key}
POST /api/sop/templates/{template_key}/versions
POST /api/sop/versions/{version_key}/publish

GET  /api/sop/runs
POST /api/sop/templates/{template_key}/runs
GET  /api/sop/runs/{run_key}
POST /api/sop/runs/{run_key}/tick
POST /api/sop/runs/{run_key}/cancel
POST /api/sop/runs/{run_key}/nodes/{node_key}/decision

POST /api/sop/derive/{mission_key}
```

## SOP permissions

```text
sop:read
sop:write
sop:publish
sop:run
sop:approve
```

`SOP:run` and `sop:approve` are execution actions and obey the emergency kill switch.

## Evaluation API

```text
GET   /api/evaluation/status
POST  /api/evaluation/tick
GET   /api/evaluation/policies
PATCH /api/evaluation/policies/{policy_key}
GET   /api/evaluation/runs
GET   /api/evaluation/runs/{evaluation_key}
GET   /api/evaluation/tasks/{task_key}
POST  /api/evaluation/tasks/{task_key}
GET   /api/evaluation/evidence
GET   /api/evaluation/replays
GET   /api/evaluation/replays/{replay_key}
POST  /api/evaluation/replays
```

## Scheduler API

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
SOP Template + Immutable Version
        ↓
SOP Run + Mission
        ↓ graph dependencies
Scheduler + Agent Registry
        ↓ governed route
Collaboration Bus
        ↓
OpenClaw / CherryAgent / Hermes / thClaws
        ↓ events, evidence and result
Evaluation Policy
        ↓ PASS / WARN / FAIL
Approval / Next Node / Rollback
        ↓
Verified SOP Outcome
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
9. SOP Builder and Workflow Templates
10. Protocol Gateway
11. Enterprise Platform
12. Executive and Business Layer
13. Scale and Marketplace

Architecture documents:

- `docs/PHASE-6-GOVERNANCE.md`
- `docs/PHASE-7-AGENT-REGISTRY.md`
- `docs/PHASE-8-SCHEDULER-ROUTER.md`
- `docs/PHASE-9-EVALUATION.md`
- `docs/PHASE-10-SOP-BUILDER.md`
- `docs/RUNTIME-INTEGRATIONS.md`
