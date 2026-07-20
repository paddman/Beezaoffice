# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is an operations-first command center where agents receive missions, join mission rooms, assign work, wait for dependencies, hand work off, follow up, request approval, verify evidence, and report results to humans.

## Current MVP

- Command Center dashboard and live organization map
- 12 founding agents with visual identities
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
  - Collaboration events projected into the live mission feed

BeezaOffice remains the command and governance plane. Connected runtimes keep their own tools, skills, memory, sessions, sandboxes and approval policies.

## Quick deploy

```bash
cp .env.example .env
# Configure BEEZA_AUTH_TOKEN and only the runtimes being used.
docker compose -f compose.yml up -d --build
```

Open:

- BeezaOffice: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- Runtime connectors: `http://localhost:8080/api/runtimes`
- Runtime event worker: `http://localhost:8080/api/runtime-event-worker`
- Collaboration worker: `http://localhost:8080/api/collaboration/worker`
- API docs: `http://localhost:8080/docs`

## Runtime and collaboration configuration

```env
CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=

BEEZA_RUNTIME_SYNC_ENABLED=true
BEEZA_RUNTIME_SYNC_INTERVAL_SECONDS=5

BEEZA_COLLAB_ENABLED=true
BEEZA_COLLAB_INTERVAL_SECONDS=3
BEEZA_COLLAB_FOLLOW_UP_SECONDS=300
BEEZA_COLLAB_MAX_FOLLOW_UPS=2
```

See `docs/RUNTIME-INTEGRATIONS.md` for all four runtime adapters and security boundaries.

## Phase 4 API

```text
POST /api/missions/{mission}/handoffs
GET  /api/missions/{mission}/collaboration
GET  /api/collaboration/tasks
POST /api/collaboration/tasks/{task}/actions
POST /api/collaboration/tasks/{task}/review
GET  /api/collaboration/inbox
POST /api/missions/{mission}/messages
GET  /api/collaboration/worker
POST /api/collaboration/tick
```

Example handoff:

```json
{
  "title": "Analyze storage evidence",
  "objective": "Review the collected evidence and return the most likely root cause.",
  "source_identity": "agent:Rei",
  "target_runtime_key": "cherryagent",
  "target_identity": "agent:infra",
  "priority": "CRITICAL",
  "review_policy": "HUMAN",
  "auto_dispatch": true,
  "depends_on": [],
  "expected_outputs": ["root cause", "evidence", "recommended action"],
  "acceptance_criteria": ["At least two evidence sources", "Confidence included"]
}
```

## Architecture

```text
Human / Manager Agent
       ↓ typed HANDOFF
Beeza Collaboration Bus
  ├─ collaboration_tasks
  ├─ collaboration_messages
  ├─ dependency resolver
  ├─ follow-up watchdog
  └─ review / revision control
       ↓
Runtime Mesh
  ├─ OpenClaw
  ├─ CherryAgent
  ├─ Hermes Agent
  └─ thClaws
       ↓
Runtime dispatch + event workers
       ↓
Mission War Room / Live Events / Mailbox
```

## Product direction

1. Workforce Kernel
2. Durable Mission Runtime
3. Collaboration Protocol
4. Organization and Chain of Command
5. Scheduler and Runtime Pool
6. Governance and Audit
7. Digital Office UI
8. Scale to 1,000 registered agents

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/RUNTIME-INTEGRATIONS.md`, `docs/PHASE-3-EVENT-STREAM.md` and `docs/PHASE-4-COLLABORATION-BUS.md`.
