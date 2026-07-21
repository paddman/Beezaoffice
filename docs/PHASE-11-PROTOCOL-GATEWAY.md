# Phase 11 — Protocol Gateway

Phase 11 exposes BeezaOffice as an interoperable, governed agent platform without allowing external clients to bypass Mission, Governance, Registry, Scheduler, Collaboration, Evaluation or SOP controls.

## Interfaces

```text
A2A 1.0 HTTP+JSON
MCP 2025-06-18 stateless JSON-RPC
OpenAI-compatible Chat Completions ingress
Bearer/HMAC Webhook ingress
Durable Server-Sent Event feed
```

All interfaces use the same internal execution path:

```text
External request
      ↓ authenticate client identity
Protocol Gateway Task
      ↓ Mission + Collaboration Task
Governance
      ↓ RBAC / clearance / budget / approval / kill switch
Scheduler + Agent Registry
      ↓
OpenClaw / CherryAgent / Hermes / thClaws
      ↓
Runtime events + evidence
      ↓
Phase 9 evaluation
      ↓
Protocol artifact and status update
```

The gateway does not forward the BeezaOffice bearer token or MCP client credentials to a downstream runtime.

## Persistent records

### `protocol_tasks`

Maps an external protocol request to BeezaOffice execution:

- Protocol and client identity
- Message and context identifiers
- A2A-style task state
- Mission key
- Collaboration task key
- Optional SOP run key
- Request envelope
- Result artifacts
- Status message, error and timestamps

A unique `(protocol, client_identity, message_id)` constraint makes request submission idempotent per client.

### `protocol_events`

Stores an ordered event sequence per protocol task:

```text
TASK_SUBMITTED
TASK_STATUS_UPDATE
TASK_ARTIFACT_UPDATE
```

These events drive A2A task subscriptions, the Command Center and the global SSE feed.

### `protocol_webhook_receipts`

Stores channel, idempotency key, payload SHA-256, client identity, mode, linked task/run and accepted response.

A repeated webhook using the same channel and idempotency key returns the existing receipt instead of creating duplicate work.

## A2A 1.0

Discovery:

```text
GET /.well-known/agent-card.json
GET /extendedAgentCard
```

The public card declares:

- HTTP+JSON interface
- A2A protocol version `1.0`
- Text and JSON input/output modes
- Streaming support
- No push-notification support in Phase 11
- Bearer authentication
- Governed task and SOP skills

Operations:

```text
POST /message:send
GET  /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}:cancel
GET  /tasks/{task_id}:subscribe
```

Clients may send:

```text
A2A-Version: 1.0
Authorization: Bearer <Beeza token>
X-Beeza-Identity: agent:external-client
```

`message:send` accepts optional routing metadata:

```json
{
  "title": "Investigate latency",
  "priority": "HIGH",
  "requiredSkills": ["metrics", "linux"],
  "requiredCapabilities": ["incident-analysis"],
  "requiredTools": ["prometheus"],
  "requiredClearance": "CONFIDENTIAL",
  "preferredRuntimeKey": "openclaw",
  "fixedRuntime": false
}
```

Default A2A execution waits for a terminal or input-required state for a bounded period. Setting `configuration.returnImmediately=true` returns the working task immediately.

### State mapping

```text
QUEUED / DISPATCHING / RUNNING / REVISION  → TASK_STATE_WORKING
WAITING_APPROVAL / REVIEW                  → TASK_STATE_INPUT_REQUIRED
COMPLETED                                  → TASK_STATE_COMPLETED
FAILED / BLOCKED / ESCALATED               → TASK_STATE_FAILED
CANCELLED                                  → TASK_STATE_CANCELED
```

Task output is returned as an artifact containing:

- Human-readable text
- Structured Beeza result envelope
- Mission and Collaboration Task references
- Runtime and dispatch provenance
- Phase 9 verification metadata

### A2A subscription

`GET /tasks/{task_id}:subscribe` returns an SSE stream:

1. Current Task as the first event
2. Ordered status updates
3. Artifact updates
4. Terminal event followed by stream closure

Task visibility is scoped to the submitting client identity. Identities with `protocol:operate` may inspect tasks across clients.

### Cancellation boundary

A2A cancellation marks the Beeza Collaboration Task canceled and prevents new work from being released. It does not claim that a remote runtime job was force-stopped. Runtime stop remains adapter-specific and may require separate approval.

## MCP

Endpoint:

```text
POST /mcp
```

Supported JSON-RPC methods:

```text
initialize
notifications/initialized
ping
tools/list
tools/call
```

The server reports protocol version:

```text
2025-06-18
```

Phase 11 is stateless: it does not require a persistent MCP session ID and does not expose server-side prompts or resources.

### MCP tools

```text
beeza_list_agents
beeza_create_task
beeza_get_task
beeza_run_sop
```

Tool-level authorization is enforced after `protocol:use`:

| Tool | Additional permission |
|---|---|
| `beeza_list_agents` | `registry:read` |
| `beeza_create_task` | `scheduler:route` |
| `beeza_get_task` | `protocol:read` |
| `beeza_run_sop` | `sop:run` |

Execution tools obey the emergency kill switch.

## OpenAI-compatible ingress

Endpoint:

```text
POST /v1/chat/completions
```

Supported model targets:

```text
beeza/auto
beeza/openclaw
beeza/cherryagent
beeza/hermes
beeza/thclaws
```

`beeza/auto` uses Phase 8 intelligent routing. A named runtime uses a fixed runtime route while retaining Governance and Collaboration controls.

Phase 11 supports `stream=false`. The gateway waits up to `BEEZA_PROTOCOL_SYNC_TIMEOUT_SECONDS`:

- Completed work returns the result artifact as assistant content.
- Longer work returns a structured accepted-task response containing task ID, mission ID, state and polling URL.

The response also includes a `beeza` extension object for clients that understand asynchronous Beeza execution.

## Webhook ingress

Endpoint pattern:

```text
POST /hooks/{channel}
```

Authentication accepts either:

1. `Authorization: Bearer <BEEZA_AUTH_TOKEN>`
2. `X-Beeza-Signature: sha256=<HMAC-SHA256>` when `BEEZA_WEBHOOK_SECRET` is configured

Modes:

```text
task → create intelligently routed protocol task
sop  → create a run from a published SOP template
```

Example task payload:

```json
{
  "mode": "task",
  "idempotency_key": "alert-2026-0721-001",
  "title": "Storage alert investigation",
  "objective": "Investigate the latency alert and return verified evidence.",
  "priority": "HIGH",
  "required_skills": ["metrics", "storage"],
  "preferred_runtime_key": "openclaw"
}
```

Example SOP payload:

```json
{
  "mode": "sop",
  "idempotency_key": "incident-7781",
  "template_key": "incident-response",
  "priority": "CRITICAL",
  "inputs": {
    "incident_summary": "Storage write latency exceeded the error threshold.",
    "affected_service": "production-storage"
  }
}
```

## Global event stream

```text
GET /api/protocol/events/stream
```

The governed SSE stream returns all protocol events using database IDs as resumable event identifiers.

Historical access:

```text
GET /api/protocol/events
GET /api/protocol/tasks
GET /api/protocol/webhook-receipts
```

## Governance

Permissions:

```text
protocol:read
protocol:use
protocol:operate
```

Default role behavior:

- Executive, Manager and Operator: read, use and operate
- Auditor: read only
- Agent: read and use
- Service: read, use and operate
- Runtime: read and use

Service identity:

```text
service:protocol
Beeza Protocol Gateway
department: Platform
clearance: RESTRICTED
role: service
```

`protocol:use` is an execution action and is blocked by the emergency kill switch.

## Configuration

```env
BEEZA_PUBLIC_URL=https://beeza.example.com
BEEZA_PROTOCOL_ENABLED=true
BEEZA_PROTOCOL_INTERVAL_SECONDS=2
BEEZA_PROTOCOL_BATCH_SIZE=100
BEEZA_PROTOCOL_SYNC_TIMEOUT_SECONDS=20
BEEZA_WEBHOOK_SECRET=
```

`BEEZA_PUBLIC_URL` must be the externally reachable HTTPS origin used in the Agent Card and polling links.

## API summary

```text
GET  /.well-known/agent-card.json
GET  /extendedAgentCard

POST /message:send
GET  /tasks
GET  /tasks/{task_id}
POST /tasks/{task_id}:cancel
GET  /tasks/{task_id}:subscribe

POST /mcp
POST /v1/chat/completions
POST /hooks/{channel}

GET  /api/protocol/status
POST /api/protocol/tick
GET  /api/protocol/tasks
GET  /api/protocol/events
GET  /api/protocol/events/stream
GET  /api/protocol/webhook-receipts
```

## Current boundaries

- A2A push-notification configuration is not implemented; polling and SSE are available.
- MCP is a stateless tools subset; resources, prompts, elicitation and OAuth discovery are deferred.
- OpenAI-compatible streaming is not implemented; A2A SSE is the streaming interface.
- Webhook channels share one optional HMAC secret in Phase 11; per-channel secret rotation belongs in the Enterprise phase.
- Gateway cancellation does not falsely report remote process termination.
- External identities must already exist in Phase 6 Governance; self-service client registration is not exposed.
