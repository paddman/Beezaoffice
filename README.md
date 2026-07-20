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
- **Phase 3 unified event stream:**
  - Server-side runtime synchronization every five seconds
  - Durable normalized runtime events in PostgreSQL
  - CherryAgent task, handoff, evidence and log capture
  - Hermes status, approval, result and usage capture
  - Mission-scoped Server-Sent Events stream
  - Live filters for tasks, handoffs, evidence, approvals and errors
  - Redis locks and bounded concurrent synchronization

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
- Event worker: `http://localhost:8080/api/runtime-event-worker`
- API docs: `http://localhost:8080/docs`

## Runtime configuration

```env
CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=

BEEZA_RUNTIME_SYNC_ENABLED=true
BEEZA_RUNTIME_SYNC_INTERVAL_SECONDS=5
BEEZA_RUNTIME_SYNC_BATCH_SIZE=100
BEEZA_RUNTIME_SYNC_CONCURRENCY=8
```

See `docs/RUNTIME-INTEGRATIONS.md` for all four runtime adapters and security boundaries.

## Phase 3 API

```text
POST /api/runtimes/{runtime}/dispatch
POST /api/runtime-dispatches/{dispatch}/sync
POST /api/runtime-dispatches/{dispatch}/stop
POST /api/runtime-dispatches/{dispatch}/approval
GET  /api/missions/{mission}/runtime-events
GET  /api/missions/{mission}/runtime-events/stream
GET  /api/runtime-event-worker
```

OpenClaw and thClaws remain synchronous adapters in this phase. CherryAgent and Hermes are synchronized by the server-side worker and projected into the unified event feed.

## Architecture

```text
Browser EventSource
  -> BeezaOffice Phase 3 API
       -> PostgreSQL
          - missions
          - runtime_dispatches
          - runtime_events
       -> Redis
          - sync locks
          - worker health
       -> Runtime Event Worker
          -> CherryAgent snapshots
          -> Hermes run status
       -> Unified mission event stream
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

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/RUNTIME-INTEGRATIONS.md` and `docs/PHASE-3-EVENT-STREAM.md`.
