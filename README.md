# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 governed AI agents.

BeezaOffice is an operations-first command center where agents receive missions, collaborate across runtimes, hold structured meetings, route work intelligently, preserve evidence, verify results, turn successful work into versioned SOPs and expose accountable work through standard agent protocols.

## Current system

- FastAPI control and protocol plane
- PostgreSQL durable state
- Redis workers, cursors and distributed locks
- Docker Compose deployment
- OpenClaw, CherryAgent, Hermes Agent and thClaws Runtime Mesh
- Mission queue, War Room, live events, approvals and audit

### Phase 2 — Runtime Control

- Runtime dispatch and status synchronization
- Remote output capture
- Hermes safe stop and approvals

### Phase 3 — Unified Event Stream

- Durable runtime events
- Server-side synchronization
- Mission-scoped SSE
- CherryAgent and Hermes event capture

### Phase 4 — Collaboration Bus

- Typed cross-runtime handoffs
- Work contracts and dependencies
- Runtime mailbox
- Human review, revision and retry
- Follow-up watchdog and escalation

### Phase 5 — Agent Meeting Manager

- Structured agendas and participant roles
- Turn-based discussion across runtimes
- Bounded rounds
- Human decision gate
- Decisions converted into action items

### Phase 6 — Governance and Identity

- Human, agent, service and runtime identities
- Scoped RBAC
- Data clearance
- Risk and cost-aware policy
- Independent approval
- Per-identity budgets
- Emergency execution kill switch
- Hash-chained audit ledger

### Phase 7 — Agent Registry and Organization Graph

- Directory designed for 1,000 logical agents
- Department and manager graph
- Lifecycle, availability and heartbeat
- Runtime/model preference
- Concurrency, workload and capacity
- Reliability, skills, capabilities and tools
- Delegation

### Phase 8 — Scheduler and Intelligent Router

- Smart tasks without a named agent
- Eligibility filtering
- Explainable weighted routing
- Runtime-pool capacity
- Cost and deadline awareness
- Retry, backpressure and failover
- Safe reroute controls

### Phase 9 — Evaluation, Verification and Replay

- Evidence-quality evaluation
- Acceptance-criteria coverage
- Runtime provenance
- Completeness, consistency and reproducibility checks
- `PASS`, `WARN` and `FAIL`
- Controlled replay and score comparison
- Verified quality blended into Registry reliability

### Phase 10 — SOP Builder and Workflow Templates

- Draft, published and deprecated lifecycle
- Immutable checksummed versions
- Dependency graph and cycle validation
- Task and human-approval nodes
- Scheduler and Collaboration integration
- Phase 9 verification gates
- Reverse-order compensation work
- Derive draft SOPs from `PASS`-verified missions

### Phase 11 — Protocol Gateway

- A2A 1.0 HTTP+JSON ingress
- Public and extended Agent Cards
- A2A task send, list, poll, cancel and SSE subscribe
- MCP `2025-06-18` stateless JSON-RPC tools subset
- OpenAI-compatible Chat Completions ingress
- Bearer or HMAC webhook task/SOP triggers
- Durable protocol event stream
- Idempotent external requests and webhook receipts
- Protocol task mapping to Mission and Collaboration Task
- Governance enforcement and audit on external execution

BeezaOffice remains the command and governance plane. Connected runtimes keep their own tools, skills, memory, sessions, sandboxes and local approval policies.

## Quick deploy

```bash
cp .env.example .env
# Set strong PostgreSQL and BeezaOffice credentials.
# Set BEEZA_PUBLIC_URL to the externally reachable HTTPS origin.
# Configure only the runtimes that will be used.
docker compose -f compose.yml up -d --build
```

Open:

- Command Center: `http://localhost:8080`
- Health: `http://localhost:8080/api/health`
- API docs: `http://localhost:8080/docs`
- Protocol status: `http://localhost:8080/api/protocol/status`
- Public Agent Card: `http://localhost:8080/.well-known/agent-card.json`
- SOP engine: `http://localhost:8080/api/sop/status`
- Evaluator: `http://localhost:8080/api/evaluation/status`
- Scheduler: `http://localhost:8080/api/scheduler/status`
- Agent Registry: `http://localhost:8080/api/registry/stats`
- Governance: `http://localhost:8080/api/governance/context`

## Core configuration

```env
BEEZA_AUTH_TOKEN=SET_A_LONG_RANDOM_TOKEN
BEEZA_PUBLIC_URL=https://beeza.example.com

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

BEEZA_SCHEDULER_ENABLED=true
BEEZA_SCHEDULER_INTERVAL_SECONDS=3
BEEZA_SCHEDULER_FAILOVER_ATTEMPTS=3

BEEZA_EVALUATOR_ENABLED=true
BEEZA_EVALUATOR_INTERVAL_SECONDS=10

BEEZA_SOP_ENABLED=true
BEEZA_SOP_INTERVAL_SECONDS=3

BEEZA_PROTOCOL_ENABLED=true
BEEZA_PROTOCOL_INTERVAL_SECONDS=2
BEEZA_PROTOCOL_SYNC_TIMEOUT_SECONDS=20
BEEZA_WEBHOOK_SECRET=
```

## Governance headers

```text
Authorization: Bearer <BEEZA_AUTH_TOKEN>
X-Beeza-Identity: human:owner
X-Beeza-Risk-Level: NORMAL
X-Beeza-Data-Classification: INTERNAL
X-Beeza-Estimated-Cost-USD: 0
X-Beeza-Approval-Key: APR-...
```

The Command Center sets these headers for governed browser operations. External A2A, OpenAI-compatible and webhook execution is also evaluated through Governance and recorded in the audit ledger.

## Seeded service identities

| Identity | Purpose |
|---|---|
| `service:runtime` | Runtime dispatch |
| `service:collaboration` | Collaboration scheduler |
| `service:meeting` | Structured meeting worker |
| `service:scheduler` | Intelligent router |
| `service:evaluator` | Evidence evaluation and replay |
| `service:sop` | SOP graph execution and rollback |
| `service:protocol` | A2A, MCP, OpenAI-compatible and webhook gateway |

## Protocol Gateway

### A2A discovery

```text
GET /.well-known/agent-card.json
GET /extendedAgentCard
```

### A2A operations

```text
POST /message:send
GET  /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}:cancel
GET  /tasks/{task_id}:subscribe
```

Example:

```bash
curl -X POST http://localhost:8080/message:send \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  -H "A2A-Version: 1.0" \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "messageId": "example-001",
      "role": "ROLE_USER",
      "parts": [{"text": "Investigate the service alert and return verified evidence."}],
      "metadata": {
        "priority": "HIGH",
        "requiredSkills": ["metrics", "evidence"]
      }
    },
    "configuration": {"returnImmediately": true}
  }'
```

### MCP

```text
POST /mcp
```

Supported methods:

```text
initialize
notifications/initialized
ping
tools/list
tools/call
```

Tools:

```text
beeza_list_agents
beeza_create_task
beeza_get_task
beeza_run_sop
```

### OpenAI-compatible ingress

```text
POST /v1/chat/completions
```

Models:

```text
beeza/auto
beeza/openclaw
beeza/cherryagent
beeza/hermes
beeza/thclaws
```

Phase 11 supports `stream=false`. Long work returns an accepted task envelope with a polling URL instead of pretending that remote execution completed synchronously.

### Webhook ingress

```text
POST /hooks/{channel}
```

Modes:

```text
task
sop
```

Authentication uses the Beeza bearer token or `X-Beeza-Signature: sha256=...` when `BEEZA_WEBHOOK_SECRET` is configured. Channel and idempotency key prevent duplicate work.

### Protocol monitoring API

```text
GET  /api/protocol/status
POST /api/protocol/tick
GET  /api/protocol/tasks
GET  /api/protocol/events
GET  /api/protocol/events/stream
GET  /api/protocol/webhook-receipts
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
External A2A / MCP / OpenAI / Webhook Client
        ↓ authentication + protocol identity
Protocol Gateway Task
        ↓
Mission + Collaboration Task or SOP Run
        ↓
Governance
        ↓
Agent Registry + Intelligent Scheduler
        ↓
OpenClaw / CherryAgent / Hermes / thClaws
        ↓
Runtime Events + Evidence
        ↓
Evaluation PASS / WARN / FAIL
        ↓
Protocol Status + Artifact + SSE
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
- `docs/PHASE-11-PROTOCOL-GATEWAY.md`
- `docs/RUNTIME-INTEGRATIONS.md`
