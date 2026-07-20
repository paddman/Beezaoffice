# Phase 3 — Unified Runtime Event Stream

Phase 3 moves synchronization from the browser into a server-side worker and turns remote runtime activity into a durable, mission-scoped event feed.

## Flow

```text
CherryAgent / Hermes
        ↓ status snapshots
Runtime Event Worker
        ↓ normalize + deduplicate
PostgreSQL runtime_events
        ↓ SSE
Mission War Room
```

## Normalized event envelope

```json
{
  "id": 42,
  "mission_key": "INC-2026-0720",
  "dispatch_key": "DSP-ABC123",
  "runtime_key": "cherryagent",
  "type": "TASK_RUNNING",
  "actor": "infra",
  "message": "Inspect storage latency · running",
  "severity": "INFO",
  "payload": {},
  "occurred_at": "2026-07-20T12:00:00Z"
}
```

## Captured activity

### CherryAgent

- Run status
- Task status changes
- Agent handoffs
- Evidence records
- Runtime logs

### Hermes Agent

- Run status
- Last lifecycle event
- Pending tool approval
- Completed result
- Final token usage

## Reliability

- PostgreSQL is the durable source of truth.
- Event keys are content-addressed to prevent duplicate inserts.
- Redis locks prevent concurrent synchronization of the same dispatch.
- The worker processes bounded batches with configurable concurrency.
- Browser SSE reconnects with the latest event ID.
- Raw payloads are bounded before storage and runtime credentials never reach the browser.

## Configuration

```env
BEEZA_RUNTIME_SYNC_ENABLED=true
BEEZA_RUNTIME_SYNC_INTERVAL_SECONDS=5
BEEZA_RUNTIME_SYNC_BATCH_SIZE=100
BEEZA_RUNTIME_SYNC_CONCURRENCY=8
```

## Operational checks

```bash
curl http://localhost:8080/api/runtime-event-worker
curl "http://localhost:8080/api/missions/INC-2026-0720/runtime-events?limit=100"
curl -N "http://localhost:8080/api/missions/INC-2026-0720/runtime-events/stream"
```

## Current boundary

OpenClaw and thClaws complete synchronously in the current adapters. Their final outputs remain visible in Mission Runtime Activity, while the unified live feed focuses on long-running CherryAgent and Hermes runs.
