# Phase 5 — Agent Meeting Manager

Phase 5 gives BeezaOffice a structured decision room instead of an unbounded group chat. Connected agents speak in a fixed order, contribute from explicit roles, stop after a configured number of rounds, and hand control to a human decision gate.

## Goal

```text
Mission evidence
      ↓
Bounded agent discussion
      ↓
Human decision
      ↓
Action items
      ↓
Collaboration Bus execution
```

A meeting is successful only when it produces:

1. A concise discussion record
2. Named options, evidence, assumptions and risks
3. Confidence scores
4. A recorded decision or executive override
5. Action items with owners and runtime targets

## Roles

| Role | Responsibility |
|---|---|
| `MODERATOR` | Keeps the room on agenda, exposes disagreement and prevents loops |
| `EXECUTIVE` | Evaluates outcome, risk, timing and organizational constraints |
| `DOMAIN` | Provides domain evidence, options and implementation constraints |
| `CRITIC` | Challenges assumptions and identifies failure modes |
| `PMO` | Converts direction into owners, deliverables, dependencies and deadlines |
| `OBSERVER` | Receives the meeting record without a speaking turn |

## Meeting state machine

```text
DRAFT
  ↓ start
RUNNING
  ├─ round 1 speaking turns
  ├─ round 2 speaking turns
  └─ maximum configured round
  ↓
AWAITING_DECISION
  ├─ ACCEPTED
  ├─ REJECTED
  └─ OVERRIDDEN
  ↓
COMPLETED
```

An operator can cancel a non-terminal meeting. An executive can record an `OVERRIDDEN` decision while discussion is still running; remaining turns are then skipped.

## Turn state machine

```text
QUEUED → DISPATCHING → RUNNING → COMPLETED
                         ├──────→ FAILED
                         └──────→ SKIPPED
```

Only one speaking turn is active in a meeting at a time. This keeps the discussion deterministic and makes replay and audit straightforward.

## Persistence

### `meetings`

Stores mission linkage, objective, agenda, status, current round, maximum rounds, decision rule, moderator, owner, summary and timestamps.

### `meeting_participants`

Stores identity, runtime, role, speaking order, required/optional state and participant-specific instructions.

### `meeting_turns`

Stores round, speaking order, prompt, runtime dispatch, contribution, confidence and lifecycle timestamps.

### `meeting_decisions`

Stores decision status, rationale, decision maker, confidence, votes, declared action items and generated Collaboration Bus task keys.

## Runtime dispatch

The meeting worker creates a normal `runtime_dispatches` record for each speaking turn. This means the existing Runtime Mesh, Phase 3 event synchronization and runtime audit remain authoritative.

```text
Meeting turn
  → OpenClaw / CherryAgent / Hermes / thClaws
  → RuntimeDispatch
  → contribution + confidence
  → next speaking turn
```

The turn prompt instructs the participant to:

- Avoid repeating previous contributions
- Name assumptions, evidence, risks and blockers
- Recommend a clear option
- Return a confidence value from `0.00` to `1.00`
- Discuss only; not execute consequential actions

## Decision to execution

An `ACCEPTED` or `OVERRIDDEN` decision can contain action items. Each action item becomes a Phase 4 `collaboration_tasks` record with:

- Runtime target
- Agent identity
- Priority
- Objective
- Expected outputs
- Acceptance criteria
- Review policy
- Optional owner and deadline

The Collaboration Bus then dispatches, follows up, escalates and reviews the work using the existing Phase 4 controls.

A `REJECTED` decision closes the meeting without creating action tasks.

## Worker configuration

```env
BEEZA_MEETING_ENABLED=true
BEEZA_MEETING_INTERVAL_SECONDS=3
BEEZA_MEETING_BATCH_SIZE=50
BEEZA_MEETING_TURN_TIMEOUT_SECONDS=900
```

The worker uses a Redis lock per meeting to prevent two processes from advancing the same room simultaneously.

## API

```text
POST /api/missions/{mission_key}/meetings
GET  /api/missions/{mission_key}/meetings
GET  /api/meetings/{meeting_key}
POST /api/meetings/{meeting_key}/start
POST /api/meetings/{meeting_key}/tick
POST /api/meetings/{meeting_key}/decision
POST /api/meetings/{meeting_key}/cancel
GET  /api/meeting-worker
POST /api/meeting-worker/tick
```

## Operational checks

```bash
curl http://localhost:8080/api/meeting-worker
curl http://localhost:8080/api/missions/INC-2026-0720/meetings
curl -X POST \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  http://localhost:8080/api/meeting-worker/tick
```

## Current boundary

- Meetings are turn-based, not free-form multi-speaker chat.
- One turn is active at a time.
- The system records participant contributions but does not automatically accept a decision.
- A human or explicitly authorized executive identity records the final decision.
- Voting is stored in the decision contract; automatic vote calculation is deferred to a later governance phase.
