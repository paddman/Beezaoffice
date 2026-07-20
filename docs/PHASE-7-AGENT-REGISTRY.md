# Phase 7 — Agent Registry and Organization Graph

Phase 7 replaces the fixed founding-agent list with a governed workforce directory designed to grow toward 1,000 registered agents without requiring 1,000 continuously running processes.

## Registry model

Each registered agent contains:

```text
Agent key
Governance identity
Display name and role title
Department and manager
Lifecycle status and live availability
Preferred runtime and model
Maximum concurrency and current workload
Reliability and run history
Skills and capabilities
Allowed tools
Data clearance
Version and owner
Profile metadata
Last heartbeat
```

Lifecycle status:

```text
ACTIVE
SUSPENDED
RETIRED
```

Availability:

```text
AVAILABLE
BUSY
WAITING
OFFLINE
MAINTENANCE
```

Status and availability are intentionally separate. An `ACTIVE` agent can be temporarily `OFFLINE`, while a `SUSPENDED` agent is blocked by Governance regardless of heartbeat.

## Organization graph

The graph contains three edge types:

```text
Department → Agent       member
Manager → Direct report  reports_to
Source → Delegate        delegates_to
```

Department nodes retain their parent department and risk tier from Phase 6 Governance. Agent nodes expose runtime, availability, reliability and utilization for operational views.

## Founding workforce migration

On the first Phase 7 startup, the 12 founding agents are migrated into `agent_registry` with:

- Governance identity linkage such as `agent:rei`
- Department keys from the governed organization
- Initial manager relationships
- Preferred OpenClaw, CherryAgent, Hermes or thClaws runtime
- Role-specific skills and allowed tools
- Initial concurrency and reliability values

The legacy `agents` table remains available for backward compatibility with the original dashboard.

## Workload reconciliation

`POST /api/registry/reconcile` projects active Collaboration Bus tasks into registry workload.

```text
Collaboration tasks
       ↓ target identity normalization
Registered agent
       ↓
current_workload
availability
available_capacity
utilization
```

The reconciliation step also expires delegations that have passed their end time.

## Reliability

Heartbeat reports can increment successful and failed run counters. Reliability is calculated from the historical prior and observed success ratio, with observed history receiving more weight as the sample grows.

Reliability is an operational routing signal, not proof that an answer is correct. Verified quality evaluation remains a later phase.

## Delegation

A delegation records:

- Source agent
- Target agent
- Permission/work scope
- Reason
- Start and optional end time
- Creating identity
- Active, expired or revoked status

Delegation does not grant Governance permissions by itself. It represents chain-of-command intent. Runtime execution still passes through Phase 6 RBAC, policy, approval, clearance, budget and kill-switch enforcement.

## Governance permissions

```text
registry:read
registry:write
registry:heartbeat
registry:delegate
```

Seeded role behavior:

- Owner: full access through `*`
- Executive and Manager: read, write and delegate
- Operator: read and heartbeat
- Auditor: read only
- Agent and Service: read and heartbeat
- Runtime: read only

Heartbeat calls are restricted to the agent's own Governance identity unless the actor also holds `registry:write`.

## API

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

Agent queries can filter by:

```text
query
department_key
status
availability
runtime_key
skill
limit
```

## Command Center

The Agent Registry surface includes:

- Workforce search
- Department, runtime, availability and skill filters
- Registered/active/capacity/utilization/reliability metrics
- Agent profile and chain of command
- Skills, capabilities and allowed tools
- Runtime preference and clearance
- Workload and heartbeat
- Organization graph grouped by department
- Skill matrix
- Delegation creation
- Agent registration, activation and suspension
- Manual workload reconciliation

## Current boundary

- Phase 7 stores preferred runtime but does not choose the best runtime automatically.
- Reliability is based on run outcomes and does not yet include evidence quality scoring.
- Delegation does not bypass Governance permissions.
- The registry supports 1,000 records, but automatic skill/cost/latency routing is deferred to Phase 8 Scheduler and Router.
