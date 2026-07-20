# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is an operations-first command center where agents receive missions, join mission rooms, assign work, wait for dependencies, hand work off, follow up, request approval, verify evidence, and report results to humans.

## Current MVP

- Command Center dashboard and live organization map
- 12 founding agents with visual identities
- Mission queue and collaboration timeline
- Agent-to-agent handoff and waiting states
- Approval and attention surfaces
- PostgreSQL and Redis state
- Docker Compose deployment
- **Agent Runtime Mesh**
  - OpenClaw Gateway
  - CherryAgent orchestrator
  - Hermes Agent Runs API
  - thClaws native `/agent/run`
- **Phase 2 runtime control**
  - Runtime run status synchronization
  - Five-second active-run polling in the selected war room
  - Remote result and error capture
  - Mission timeline updates when remote status changes
  - Hermes safe stop
  - Hermes human approval and denial controls

BeezaOffice is the command/governance plane. Connected runtimes keep their own tools, skills, memory, sessions, sandboxes, and approval policies.

## Quick deploy

```bash
cp .env.example .env
# Configure BEEZA_AUTH_TOKEN and any runtime base URLs/tokens.
docker compose -f compose.yml up -d --build
```

Open:

- BeezaOffice: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- Runtime connectors: `http://localhost:8080/api/runtimes`
- API docs: `http://localhost:8080/docs`

## Runtime configuration

Add the runtimes being used to `.env`:

```env
OPENCLAW_BASE_URL=http://openclaw-host:18789
OPENCLAW_AUTH_TOKEN=replace-me
OPENCLAW_AGENT_TARGET=openclaw/default

CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=replace-me

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=replace-me

THCLAW_BASE_URL=http://thclaws-host:7878
THCLAW_AUTH_TOKEN=replace-me
THCLAW_WORKSPACE_DIR=/var/thcompany/agents/beeza-worker
```

See `docs/RUNTIME-INTEGRATIONS.md` for runtime-side setup and security boundaries.

## Runtime control API

```text
POST /api/runtimes/{runtime}/dispatch
POST /api/runtime-dispatches/{dispatch}/sync
POST /api/runtime-dispatches/{dispatch}/stop
POST /api/runtime-dispatches/{dispatch}/approval
GET  /api/runtime-dispatches?mission_key=...
```

Phase 2 intentionally keeps OpenClaw and thClaws dispatches synchronous. CherryAgent and Hermes long-running runs can be polled; Hermes additionally exposes safe stop and approval controls.

## Architecture

```text
Browser
  -> BeezaOffice FastAPI Command Center
       -> PostgreSQL (missions, runtime registry, dispatch audit)
       -> Redis (queue, counters, presence, sync locks)
       -> Agent Runtime Mesh
            -> OpenClaw
            -> CherryAgent
            -> Hermes Agent
            -> thClaws
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

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/RUNTIME-INTEGRATIONS.md`.
