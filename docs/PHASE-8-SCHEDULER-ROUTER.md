# Phase 8 — Scheduler and Intelligent Router

Phase 8 turns the Phase 7 workforce registry into an execution scheduler. A smart task can declare the work it needs without naming a specific agent or runtime. BeezaOffice evaluates the current organization and runtime pool, records the evidence behind the decision, and sends the work through the existing governed Collaboration Bus.

## Routing flow

```text
Smart task
   ↓ requirements
Scheduler policy
   ↓ hard eligibility filters
Agent Registry + Runtime Pool
   ↓ weighted score
Routing decision
   ↓ selected agent/runtime/model
Governed Collaboration Dispatch
   ↓ runtime failure
Failover exclusion and reroute
```

## Hard eligibility filters

A candidate is rejected before scoring when any required boundary fails:

- Registry lifecycle status is not `ACTIVE`
- Availability is `OFFLINE` or `MAINTENANCE`
- Agent clearance is below the task classification
- Preferred runtime is missing or unconfigured
- Agent concurrency is full and overflow is disabled
- Runtime pool capacity is full and overflow is disabled
- Required skill coverage is below policy minimum
- Strict skill, capability or tool matching fails
- Estimated runtime cost exceeds the task ceiling
- Agent or runtime was excluded by a prior failed route or operator reroute

Clearance order:

```text
PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED
```

## Weighted score

The default balanced policy uses:

| Component | Weight |
|---|---:|
| Skill/capability/tool coverage | 28% |
| Reliability | 20% |
| Available agent capacity | 18% |
| Runtime health and latency | 14% |
| Estimated cost | 10% |
| Deadline response | 6% |
| Department/runtime/agent affinity | 4% |

Weights are normalized when a policy is evaluated. A policy can be changed without rebuilding the application.

## Runtime pool

The runtime pool is calculated from `runtime_connectors` and active `runtime_dispatches`.

```text
OpenClaw     default 25 slots
CherryAgent default 50 slots
Hermes      default 25 slots
thClaws     default 25 slots
```

Each pool record includes:

- Configured and online state
- Active dispatch count
- Capacity limit and available slots
- Utilization
- Last latency and error
- Model
- Estimated cost per 1,000 tokens

Limits and cost rates live in the scheduler policy and can be adjusted through the API.

## Smart task contract

A routed task can declare:

```text
Objective and priority
Required skills
Required capabilities
Required tools
Required data clearance
Preferred department
Preferred runtime
Estimated tokens
Maximum cost
Strict matching
Capacity overflow policy
Deadline
Expected outputs
Acceptance criteria
Review policy
```

The task is initially addressed to:

```text
agent:auto
runtime: auto
```

After selection, the task is rewritten to the chosen governed agent identity and runtime before the normal Collaboration Bus dispatch starts.

## Routing decisions

Every routing attempt creates a durable `routing_decisions` record containing:

- Mission and task
- Policy
- Attempt number
- Status: `SELECTED`, `WAITING`, `NO_ROUTE`, or `OVERRIDDEN`
- Selected agent, runtime, model and score
- Original request
- Ranked candidate evidence
- Acceptance or rejection reasons
- Creating identity and timestamp

This makes routing explainable and replayable instead of hiding the choice inside an LLM prompt.

## Backpressure

When no candidate is eligible:

1. Task remains queued
2. A `WAITING` routing decision is recorded
3. Retry time is stored in task context
4. Scheduler retries after the policy interval
5. After the maximum route attempts, task becomes `BLOCKED`

Default policy:

```text
Retry every 30 seconds
Maximum 5 routing attempts
```

## Failover

When a selected runtime dispatch fails:

1. The failed agent and runtime are appended to exclusion lists
2. Task is returned to `QUEUED`
3. Routing status becomes `WAITING`
4. Scheduler selects the next eligible candidate
5. Original failed dispatch remains in the audit history

Default failover limit is three automatic failovers.

An operator can request rerouting for a queued, blocked, escalated or revision task. Rerouting is refused while a task is `DISPATCHING`, `RUNNING`, `WAITING_APPROVAL` or `REVIEW`, because starting a second route could duplicate execution.

## Registry workload

The scheduler runs Phase 7 workload reconciliation before each routing batch. Active Collaboration Bus tasks are projected onto agent concurrency.

Logical agents do not become offline simply because no heartbeat implementation is configured. Stale-heartbeat enforcement is activated only for profiles with:

```json
{"heartbeat_required": true}
```

## Governance permissions

```text
scheduler:read
scheduler:route
scheduler:policy:write
```

Role defaults:

- Owner: full access through wildcard
- Executive: read, route and policy update
- Manager and Operator: read and route
- Auditor: read only
- Agent: read only
- Service: read and route
- Runtime: read only

All smart-task creation, rerouting, manual ticks and policy updates are handled by Phase 6 Governance and written to the audit ledger.

## API

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

## Worker configuration

```env
BEEZA_SCHEDULER_ENABLED=true
BEEZA_SCHEDULER_INTERVAL_SECONDS=3
BEEZA_SCHEDULER_BATCH_SIZE=100
BEEZA_SCHEDULER_FAILOVER_ATTEMPTS=3
```

## Operational checks

```bash
curl http://localhost:8080/api/health

curl \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  http://localhost:8080/api/scheduler/status

curl \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  http://localhost:8080/api/scheduler/runtime-pool
```

Manual scheduler tick:

```bash
curl -X POST \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  http://localhost:8080/api/scheduler/tick
```

## Current boundary

- Runtime cost is an operator-configured estimate, not a provider invoice.
- Reliability uses Phase 7 run history and is not yet an evidence-quality score.
- Preferred model is selected and recorded but adapters still use their configured runtime model.
- Scheduling is deterministic weighted ranking, not a learned routing model.
- Quality evaluation, result verification and replay are deferred to Phase 9.
