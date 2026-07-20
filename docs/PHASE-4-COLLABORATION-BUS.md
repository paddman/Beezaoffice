# Phase 4 — Cross-runtime Collaboration Bus

Phase 4 turns BeezaOffice from a runtime dashboard into a shared office where agents can assign work, wait for dependencies, follow up, return results and request revisions across different agent platforms.

## Core contract

Every handoff is stored as a durable work contract:

```json
{
  "task_key": "TASK-AB12CD34EF56",
  "mission_key": "INC-2026-0720",
  "source_identity": "agent:Rei",
  "target_identity": "agent:infra",
  "target_runtime_key": "cherryagent",
  "status": "RUNNING",
  "depends_on": [],
  "expected_outputs": ["root cause", "evidence", "recommended action"],
  "acceptance_criteria": ["At least two evidence sources"],
  "review_policy": "HUMAN"
}
```

## Collaboration lifecycle

```text
HANDOFF_CREATED
  → WAITING_DEPENDENCY
  → QUEUED
  → DISPATCHING
  → RUNNING
  → WAITING_APPROVAL (optional)
  → REVIEW (optional)
  → COMPLETED
```

Failure paths:

```text
BLOCKED
FAILED
CANCELLED
ESCALATED
REVISION → dispatch again
```

## Typed mailbox messages

The mission mailbox supports:

- ASSIGN
- ACCEPT / REJECT
- REQUEST_INFO / RESPONSE
- HANDOFF
- REVIEW / REVISION
- BLOCKED
- FOLLOW_UP
- DECISION
- FYI
- ESCALATION
- COMPLETION

Delivery states are stored independently from task status:

```text
CREATED → DELIVERED → SEEN → ACCEPTED → IN_PROGRESS → RESPONDED
```

## Dependency engine

A task with dependencies remains `WAITING_DEPENDENCY` until every referenced task reaches `COMPLETED`. The collaboration worker then moves it to `QUEUED` and dispatches it automatically when `auto_dispatch=true`.

## Runtime dispatch

The same work-contract envelope is converted into each runtime's native API:

- OpenClaw: synchronous OpenAI-compatible completion
- CherryAgent: asynchronous orchestrator run
- Hermes Agent: asynchronous Runs API
- thClaws: synchronous `/agent/run`

Long-running CherryAgent and Hermes dispatches are synchronized by Phase 3. Phase 4 mirrors their final state into the collaboration task and releases dependent work.

## Follow-up watchdog

The worker tracks `next_follow_up_at`, `follow_up_count` and `deadline_at`.

```text
No progress before follow-up threshold
  → FOLLOW_UP message
  → second FOLLOW_UP
  → ESCALATION to Beeza Operator
```

A missed deadline escalates immediately.

Configuration:

```env
BEEZA_COLLAB_ENABLED=true
BEEZA_COLLAB_INTERVAL_SECONDS=3
BEEZA_COLLAB_BATCH_SIZE=100
BEEZA_COLLAB_FOLLOW_UP_SECONDS=300
BEEZA_COLLAB_MAX_FOLLOW_UPS=2
```

## Review and revision

`review_policy=AUTO` closes a task when its runtime dispatch completes.

`review_policy=HUMAN` moves the task to `REVIEW`, where the manager can:

- Accept → COMPLETED
- Revise → REVISION → new dispatch
- Reject → FAILED

## Durable storage

PostgreSQL tables:

```text
collaboration_tasks
collaboration_messages
runtime_dispatches
runtime_events
mission_events
```

Redis is used for worker state and runtime synchronization locks.

## API checks

```bash
curl http://localhost:8080/api/collaboration/worker
curl http://localhost:8080/api/missions/INC-2026-0720/collaboration
curl 'http://localhost:8080/api/collaboration/inbox?mission_key=INC-2026-0720'
```

Run one scheduler cycle manually:

```bash
curl -X POST \
  -H 'Authorization: Bearer YOUR_BEEZA_TOKEN' \
  http://localhost:8080/api/collaboration/tick
```

## Phase boundary

Phase 4 provides reliable BeezaOffice-mediated collaboration. It does not yet implement a universal external A2A protocol or direct peer-to-peer runtime sockets. All handoffs pass through BeezaOffice so governance, evidence and audit remain centralized.
