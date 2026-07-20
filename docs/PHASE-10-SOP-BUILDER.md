# Phase 10 — SOP Builder and Workflow Templates

Phase 10 converts verified work into repeatable, governed operating procedures. An SOP is not a prompt preset; it is a versioned dependency graph that creates a mission, routes work through the Agent Registry and Scheduler, pauses at human approvals, waits for Phase 9 verification and executes compensation tasks when a later step fails.

## Execution flow

```text
Published SOP version
        ↓ validate inputs and immutable checksum
SOP Run + Mission
        ↓
Ready graph nodes
        ├─ TASK → Scheduler / Collaboration Bus → Runtime Mesh
        └─ APPROVAL → Human decision gate
        ↓
Phase 9 evidence evaluation
        ├─ PASS → node complete
        ├─ WARN → human approval
        └─ FAIL → workflow failure
        ↓
Next dependency-ready nodes
        ↓
Complete or rollback
```

## Data model

### `sop_templates`

Stores the stable procedure identity:

- Template key and display name
- Description and category
- Lifecycle status
- Current version number
- JSON input schema
- Tags and owner identity

### `sop_versions`

Stores immutable workflow versions:

- Template and version number
- Draft, published or deprecated state
- Full validated definition
- SHA-256 canonical checksum
- Changelog and creator
- Publication timestamp

Publishing a draft deprecates the previous published version. Existing runs retain their original version key and definition.

### `sop_runs`

Stores one execution instance:

- Template and version
- Generated mission key
- Inputs and collected outputs
- Active node
- Status, failure reason and timestamps
- Starting Governance identity

### `sop_node_runs`

Stores each node execution:

- SOP run and node identity
- Task, approval or rollback type
- Collaboration task link
- Input and output snapshots
- Attempts, error and lifecycle timestamps

## Template state

```text
DRAFT → PUBLISHED → DEPRECATED
```

A template may have a new draft while an older published version remains executable. Only published versions can start runs.

## Run state

```text
PENDING
   ↓
RUNNING
   ├─ WAITING_APPROVAL
   ├─ ROLLING_BACK
   ├─ COMPLETED
   ├─ FAILED
   └─ CANCELLED
```

## Node state

```text
PENDING → RUNNING → COMPLETED
                 ├→ WAITING_APPROVAL
                 └→ FAILED

Rollback nodes:
RUNNING → ROLLED_BACK
        └→ FAILED
```

## Definition format

```json
{
  "rollback_on_failure": true,
  "stop_on_failure": true,
  "settings": {},
  "nodes": [
    {
      "key": "collect-evidence",
      "title": "Collect evidence",
      "node_type": "TASK",
      "depends_on": [],
      "objective": "Collect evidence for {{input.service}}.",
      "routing_mode": "AUTO",
      "priority": "HIGH",
      "review_policy": "AUTO",
      "required_skills": ["metrics", "evidence"],
      "required_capabilities": [],
      "required_tools": ["prometheus"],
      "required_clearance": "INTERNAL",
      "expected_outputs": ["timeline", "metric evidence"],
      "acceptance_criteria": ["Sources have timestamps"],
      "verification_required": true
    },
    {
      "key": "approve-change",
      "title": "Approve change",
      "node_type": "APPROVAL",
      "depends_on": ["collect-evidence"],
      "objective": "Approve the evidence-backed change.",
      "verification_required": false
    },
    {
      "key": "execute-change",
      "title": "Execute change",
      "node_type": "TASK",
      "depends_on": ["approve-change"],
      "objective": "Execute the approved change for {{input.service}}.",
      "routing_mode": "AUTO",
      "priority": "CRITICAL",
      "verification_required": true,
      "rollback": {
        "title": "Rollback change",
        "objective": "Restore the previous known-good state for {{input.service}}.",
        "acceptance_criteria": ["Previous state restored"]
      }
    }
  ]
}
```

## Variable rendering

The engine supports bounded substitution in objectives, inputs, outputs and criteria:

```text
{{input.service}}
{{input.change_window}}
{{run.key}}
{{mission.key}}
{{mission.title}}
{{node.collect-evidence}}
```

Node output references expose the prior node's output payload. Missing variables remain visible instead of silently becoming empty strings.

## Validation

Before a draft is stored or published, BeezaOffice checks:

- Unique node keys
- Valid dependency references
- No self-dependencies
- Directed acyclic graph
- Required task objectives
- Fixed routes have a runtime target
- Maximum 100 nodes
- Canonical checksum matches the stored definition at publication

## Task nodes

A task node becomes a normal Phase 4 `collaboration_tasks` record.

Automatic routing declares:

```text
target_identity = agent:auto
target_runtime = auto
```

The node passes skills, capabilities, tools, clearance, department affinity, runtime preference, token estimate and cost ceiling into Phase 8 Scheduler context.

Fixed routing uses the specified agent and runtime but still passes through Phase 6 Governance and the runtime approval boundary.

## Verification gate

When `verification_required=true`, runtime completion is not enough:

```text
No evaluation yet → node remains RUNNING
PASS              → node COMPLETED
WARN              → node WAITING_APPROVAL
FAIL              → node FAILED
```

The SOP worker therefore waits for the Phase 9 evaluator rather than trusting the remote `COMPLETED` status.

## Human decisions

Approval nodes and warning/review task nodes use:

```text
POST /api/sop/runs/{run_key}/nodes/{node_key}/decision
```

Decision values:

```text
approve
reject
```

Approval can release dependent work, so `sop:approve` is treated as an execution permission and obeys the emergency kill switch.

## Rollback

When a node fails and `rollback_on_failure=true`, completed nodes with rollback definitions are compensated in reverse topological order.

```text
A completed
B completed
C failed
    ↓
rollback B
    ↓
rollback A
    ↓
run FAILED with rollback evidence
```

Rollback work is represented as ordinary Collaboration Bus tasks and remains visible in the Runtime Event feed. A failed rollback terminates the rollback sequence and records the failure reason.

A completed rollback does not convert the original run to success. It leaves the run `FAILED` because the intended procedure did not complete, while documenting that compensation succeeded.

## Cancellation boundary

Cancelling an SOP prevents new nodes from being released and marks pending nodes cancelled. It does not force-kill remote executions that were already dispatched. Runtime stop controls remain separate because killing active external work requires adapter-specific confirmation and approval.

## Deriving an SOP from verified work

```text
POST /api/sop/derive/{mission_key}
```

BeezaOffice reads the mission's Collaboration Tasks and includes only tasks whose latest Phase 9 evaluation is `PASS`.

The derived draft preserves:

- Task dependency graph
- Objective
- Routing mode and selected route where fixed
- Skills, capabilities and tools
- Clearance and cost constraints
- Expected outputs and acceptance criteria
- Review policy

The result is always a draft. An operator must inspect and publish it before execution.

## Seeded procedures

Phase 10 seeds:

### Verified Incident Response

```text
Collect evidence
→ Analyze root cause
→ Human approval
→ Execute remediation
→ Verify recovery
→ Publish incident report
```

The remediation node includes rollback.

### Daily Operations Brief

```text
Collect service health ─┐
                        ├→ Compose executive brief
Collect risk/approvals ─┘
```

## Governance

Permissions:

```text
sop:read
sop:write
sop:publish
sop:run
sop:approve
```

Default behavior:

- Executive: full SOP control
- Manager: read, write, run and approve
- Operator: read, run and approve
- Auditor: read only
- Agent and Runtime: read only
- Service: read and run

The service principal is:

```text
service:sop
Beeza SOP Orchestrator
department: Operations
clearance: RESTRICTED
role: service
```

## Worker

```env
BEEZA_SOP_ENABLED=true
BEEZA_SOP_INTERVAL_SECONDS=3
BEEZA_SOP_BATCH_SIZE=100
```

The worker uses a Redis lock per SOP run, advances bounded batches and stores health state in `beezaoffice:sop-worker`.

## API

```text
GET  /api/sop/status
POST /api/sop/tick

GET  /api/sop/templates
POST /api/sop/templates
GET  /api/sop/templates/{template_key}
POST /api/sop/templates/{template_key}/versions
POST /api/sop/versions/{version_key}/publish

GET  /api/sop/runs
POST /api/sop/templates/{template_key}/runs
GET  /api/sop/runs/{run_key}
POST /api/sop/runs/{run_key}/tick
POST /api/sop/runs/{run_key}/cancel
POST /api/sop/runs/{run_key}/nodes/{node_key}/decision

POST /api/sop/derive/{mission_key}
```

## Command Center

The SOP Builder provides:

- Template library
- Draft/published/deprecated versions
- Checksum and changelog
- Workflow node graph
- Input-schema-driven run form
- Run and mission history
- Node/task/evaluation state
- Human approve/reject controls
- Manual worker advance
- Cancellation warning for already-dispatched work
- Derive SOP from the selected PASS-verified mission

## Current boundaries

- The graph supports task and approval nodes; conditional branching is deferred.
- Manual and API triggers are supported; cron and webhook trigger gateways are deferred to Phase 11.
- Rollback tasks are compensation work, not database transactions.
- Cancellation does not force-stop already-running remote jobs.
- Visual editing currently uses validated JSON definitions rather than a drag-and-drop canvas.
