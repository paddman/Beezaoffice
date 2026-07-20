# Phase 9 — Evaluation, Verification and Replay

Phase 9 adds a quality-control plane after runtime execution. A task is not trusted only because an external runtime reports `COMPLETED`; BeezaOffice records the result, evaluates its evidence, exposes the decision to humans and can replay the same work through a controlled route.

## Evaluation flow

```text
Runtime result
    ↓
Collaboration task reaches COMPLETED / REVIEW / FAILED / BLOCKED
    ↓
Evidence evaluator
    ├─ completeness
    ├─ acceptance-criteria coverage
    ├─ supporting evidence
    ├─ runtime provenance
    ├─ status/result consistency
    ├─ reproducibility
    └─ risk and rollback disclosure
    ↓
PASS / WARN / FAIL
    ↓
AUTO_ACCEPT / HUMAN_ACCEPT / HUMAN_REVIEW / REVISE_OR_REPLAY
```

The current evaluator is a deterministic policy baseline. It does not claim semantic proof. Later evaluators can add model-based judges, executable tests, domain-specific validators and independent verifier agents while preserving the same evaluation ledger.

## Data model

### Evaluation policy

An evaluation policy stores:

- Component weights
- Pass and warning thresholds
- Minimum supporting evidence
- Provenance requirement
- Acceptance-coverage requirement
- Whether a failed automatically completed task is reopened for review
- Additional evaluator settings

The seeded policy is `policy:evidence-baseline`.

Default component weights:

```text
Completeness          20%
Acceptance coverage   20%
Supporting evidence   20%
Runtime provenance    15%
Consistency           10%
Reproducibility       10%
Risk disclosure        5%
```

Default thresholds:

```text
PASS  >= 0.78 with no hard error
WARN  >= 0.55 without a provenance/status conflict
FAIL  below warning threshold or a hard verification conflict
```

### Evaluation run

Every run records:

- Mission and task
- Policy and evaluator identity
- Result hash
- Source task status and dispatch key
- Overall score
- Component scores
- Findings
- Evidence count
- Recommendation
- Bounded source snapshot
- Creation time

The source hash prevents the background worker from repeatedly evaluating an unchanged result. The hash excludes BeezaOffice's own `verification` metadata and volatile task timestamps, so writing an evaluation does not trigger another evaluation loop. A human can request a forced evaluation to create a new auditable run without repeatedly changing the agent reliability score.

### Evidence record

Evidence is normalized into independent records:

```text
CLAIM
EVIDENCE
SOURCE
REFERENCE
ARTIFACT
COMMAND
CHECK
PROVENANCE
```

Each record stores a title, locator, SHA-256 content hash, strength and bounded metadata. The completion summary is stored as a claim but does not count as supporting evidence by itself.

### Replay run

A replay links:

- Original task
- Replay task
- Replay mode
- Requester and reason
- Immutable source snapshot
- Current replay state
- Original/replay evaluation comparison

Replay modes:

```text
SAME      Reproduce the original agent/runtime route
REROUTE   Exclude the previous route and choose another candidate
FAILOVER  Re-enter the scheduler failover path
```

Replays use `HUMAN` review policy to prevent an independent verification run from silently replacing the original conclusion.

## Completion gate behavior

The evaluator writes a compact verification block back into the task result:

```json
{
  "verification": {
    "evaluation_key": "EVAL-...",
    "status": "PASS",
    "score": 0.84,
    "recommendation": "AUTO_ACCEPT",
    "evidence_count": 3,
    "evaluated_at": "..."
  }
}
```

When an automatically completed task receives `FAIL` and the policy enables reopening, BeezaOffice moves the task to `REVIEW` and sets the mission to wait for a human verification decision.

A warning does not automatically fail the task. It recommends human review and remains visible in the Evaluation Center.

## Agent quality signal

A new evaluation updates the assigned registry agent's quality profile:

```text
evaluation_quality.total
evaluation_quality.pass
evaluation_quality.warn
evaluation_quality.fail
evaluation_quality.last_score
evaluation_quality.last_evaluation_key
```

The registry reliability score is blended slowly toward the verified score. This avoids a single heuristic evaluation causing a large routing change while still allowing Phase 8 routing to learn from evidence quality over time.

## Governance

Permissions:

```text
evaluation:read
evaluation:run
evaluation:policy:write
replay:create
```

Correct separation:

```text
evaluation:read          Read evaluation, evidence and replay history
evaluation:run           Run deterministic local evaluation
evaluation:policy:write  Change evaluator thresholds and weights
replay:create            Create a second runtime execution
```

`replay:create` is an execution action. It obeys the Phase 6 emergency kill switch because it can enqueue a second external run. Evaluation itself is local verification and can continue while runtime execution is paused.

The default service principal is:

```text
service:evaluator
Beeza Evidence Evaluator
department: Quality
clearance: RESTRICTED
role: service
```

## Worker

The evaluator worker scans a bounded batch of tasks in:

```text
COMPLETED
REVIEW
FAILED
BLOCKED
```

It evaluates only unseen stable result hashes, updates replay states, writes worker status to Redis and sleeps for the configured interval.

Environment settings:

```env
BEEZA_EVALUATOR_ENABLED=true
BEEZA_EVALUATOR_INTERVAL_SECONDS=10
BEEZA_EVALUATOR_BATCH_SIZE=100
```

## API

```text
GET   /api/evaluation/status
POST  /api/evaluation/tick

GET   /api/evaluation/policies
PATCH /api/evaluation/policies/{policy_key}

GET   /api/evaluation/runs
GET   /api/evaluation/runs/{evaluation_key}
GET   /api/evaluation/tasks/{task_key}
POST  /api/evaluation/tasks/{task_key}
GET   /api/evaluation/evidence

GET   /api/evaluation/replays
GET   /api/evaluation/replays/{replay_key}
POST  /api/evaluation/replays
```

## Command Center

The Evaluation Center provides:

- Pass rate and average score
- Warning and failure counts
- Open human review count
- Worker status and policy thresholds
- Evaluation runs by selected mission
- Component score bars
- Findings and rejection reasons
- Evidence and provenance chain
- Manual forced evaluation
- Controlled replay creation
- Replay status and score comparison

## Current boundaries

- Acceptance coverage is deterministic token/phrase matching, not semantic proof.
- Evidence strength is structural and provenance-based; it does not independently verify that an external document is true.
- Replay comparison uses evaluation scores and components, not a full semantic diff.
- Domain-specific validators, executable checks, independent judge agents and dataset-based regression suites are deferred to later phases.
