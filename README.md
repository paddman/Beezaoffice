# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is an operations-first command center where agents receive missions, join mission rooms, assign work, wait for dependencies, hand work off, follow up, request approval, hold structured meetings, record decisions, verify evidence, and report results to humans.

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
- **Phase 5 agent meeting manager:**
  - Structured agenda and role-based participants
  - Turn-based discussion across connected runtimes
  - Bounded rounds to prevent repetitive agent loops
  - Moderator, executive, domain, critic, PMO and observer roles
  - Confidence score capture per contribution
  - Human decision gate with accept, reject and executive override
  - Accepted decisions converted into Collaboration Bus action items
  - Meeting events projected into the live mission feed

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
- Meeting worker: `http://localhost:8080/api/meeting-worker`
- API docs: `http://localhost:8080/docs`

## Runtime, collaboration and meeting configuration

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

BEEZA_MEETING_ENABLED=true
BEEZA_MEETING_INTERVAL_SECONDS=3
BEEZA_MEETING_BATCH_SIZE=50
BEEZA_MEETING_TURN_TIMEOUT_SECONDS=900
```

See `docs/RUNTIME-INTEGRATIONS.md` for all four runtime adapters and security boundaries.

## Phase 5 API

```text
POST /api/missions/{mission}/meetings
GET  /api/missions/{mission}/meetings
GET  /api/meetings/{meeting}
POST /api/meetings/{meeting}/start
POST /api/meetings/{meeting}/tick
POST /api/meetings/{meeting}/decision
POST /api/meetings/{meeting}/cancel
GET  /api/meeting-worker
POST /api/meeting-worker/tick
```

Example meeting:

```json
{
  "title": "Incident remediation decision",
  "objective": "Review the verified evidence, challenge the options and decide a safe remediation plan.",
  "agenda": [
    "Review evidence",
    "Compare options and failure modes",
    "Select decision",
    "Assign action items"
  ],
  "max_rounds": 2,
  "decision_rule": "EXECUTIVE",
  "moderator_identity": "agent:Beeza Moderator",
  "owner_identity": "agent:Rei",
  "participants": [
    {
      "identity": "agent:Beeza Moderator",
      "runtime_key": "cherryagent",
      "role": "MODERATOR"
    },
    {
      "identity": "agent:Infrastructure Specialist",
      "runtime_key": "openclaw",
      "role": "DOMAIN"
    },
    {
      "identity": "agent:Devil's Advocate",
      "runtime_key": "hermes",
      "role": "CRITIC"
    },
    {
      "identity": "agent:PMO",
      "runtime_key": "thclaws",
      "role": "PMO"
    }
  ]
}
```

Example decision:

```json
{
  "title": "Approve staged remediation",
  "rationale": "The staged option has the strongest evidence and the lowest rollback risk.",
  "status": "ACCEPTED",
  "decided_by": "agent:Rei",
  "confidence": 0.88,
  "votes": {},
  "action_items": [
    {
      "title": "Execute staged remediation",
      "objective": "Apply the approved change, preserve evidence and verify service recovery.",
      "target_runtime_key": "openclaw",
      "target_identity": "agent:infra",
      "priority": "CRITICAL",
      "review_policy": "HUMAN",
      "expected_outputs": ["change evidence", "verification result"],
      "acceptance_criteria": ["service recovered", "rollback remains available"]
    }
  ]
}
```

## Architecture

```text
Mission
  ↓
Structured Meeting Manager
  ├─ meetings
  ├─ meeting_participants
  ├─ meeting_turns
  ├─ meeting_decisions
  ├─ bounded round scheduler
  └─ human decision gate
       ↓ role-specific speaking turns
Runtime Mesh
  ├─ OpenClaw
  ├─ CherryAgent
  ├─ Hermes Agent
  └─ thClaws
       ↓ contributions + confidence
Meeting Decision
       ↓ accepted action items
Collaboration Bus
       ↓ execution + follow-up + review
Mission War Room / Live Events
```

## Product direction

1. Workforce Kernel
2. Durable Mission Runtime
3. Collaboration Protocol
4. Structured Meetings and Decisions
5. Organization and Chain of Command
6. Scheduler and Runtime Pool
7. Governance and Audit
8. Digital Office UI
9. Scale to 1,000 registered agents

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/RUNTIME-INTEGRATIONS.md`, `docs/PHASE-3-EVENT-STREAM.md`, `docs/PHASE-4-COLLABORATION-BUS.md` and `docs/PHASE-5-MEETING-MANAGER.md`.
