# BeezaOffice 0.16.1 — Agent Rooms

Version `0.16.1` gives every governed Agent a persistent personal workspace. The Room is the human-facing operating surface above Registry, Collaboration, Meetings, Runtime Dispatch and Evaluation.

## Product model

```text
Registered Agent
      ↓
Persistent Agent Room
      ├── Work Desk
      ├── Direct Inbox
      ├── Meetings
      ├── Notes & curated memory
      ├── Evaluation summary
      ├── Runtime activity
      └── Replaceable visual scene
```

An Agent Room is not another Runtime process. It is a persistent control-plane view and interaction boundary for an Agent identity.

## Automatic provisioning

Rooms are created lazily for registered Agents and seeded for the default Tenant at application startup.

The Room keeps a deterministic relationship to:

- Tenant
- Agent Registry key
- Governed Agent identity
- Department and clearance
- Preferred Runtime
- Personal persistent Room Mission

Creating a new Registry Agent does not require a separate Room provisioning call. The Room is created when the directory or Agent Room is first opened.

## Room API

```text
GET    /api/agent-rooms/status
GET    /api/agent-rooms
GET    /api/agent-rooms/{agent_key}
PATCH  /api/agent-rooms/{agent_key}
POST   /api/agent-rooms/{agent_key}/messages
POST   /api/agent-rooms/{agent_key}/tasks
POST   /api/agent-rooms/{agent_key}/notes
DELETE /api/agent-rooms/{agent_key}/notes/{note_key}
```

Directory filters:

```text
department_key
availability
```

## Work Desk

Assigning work from a Room creates a real `CollaborationTask` with:

- Fixed Agent identity
- Agent preferred Runtime
- Priority and review policy
- Expected outputs
- Acceptance criteria
- Optional deadline
- Agent Room context
- Optional immediate dispatch

The task remains part of the existing Collaboration, Runtime Event, Evaluation and Audit systems.

The first direct Room interaction creates a persistent personal Mission for that Agent. It is used as the durable collaboration container for Room messages and Room-assigned tasks.

## Direct Inbox

A Room message creates a standard `CollaborationMessage` delivered to the Agent identity.

Supported types:

```text
REQUEST_INFO
FYI
```

A delivered Room message does not claim that the Runtime has already answered. Response behavior depends on the connected Agent platform and worker integration.

## Meetings

The Room lists Meetings where the Agent identity is an active participant. Meeting lifecycle, turn order and decisions continue to use the existing Structured Meeting Manager.

## Notes and curated memory

Room notes support:

```text
NOTE
MEMORY
REMINDER
```

Notes can be pinned and are Tenant scoped using the Agent clearance classification.

This feature is deliberately curated. It is not an unrestricted autonomous memory store and does not silently ingest every conversation.

## Evaluation and activity

Room detail aggregates:

- Latest Evaluation per Agent task
- PASS, WARN and FAIL counters
- Runtime Dispatch state
- Task updates
- Direct messages
- Meetings
- Notes and memory

These are rendered as one Room Activity timeline.

## Visual mock and asset replacement

Version `0.16.1` ships generic placeholder assets:

```text
app/static/assets/agent-room-placeholder.svg
app/static/assets/agent-avatar-placeholder.svg
```

Every Room also exposes the expected custom paths:

```text
app/static/assets/agent-rooms/<agent-key>/background.webp
app/static/assets/agent-rooms/<agent-key>/avatar.webp
app/static/assets/agent-rooms/<agent-key>/foreground.webp
```

Recommended files:

| Layer | Size | Notes |
|---|---:|---|
| Background | 1920×1080 | Full Room scene, WebP |
| Avatar | 1024×1024 | Transparent PNG or WebP |
| Foreground | 1920×1080 | Optional transparent furniture/effect overlay |

Example for Mira:

```text
app/static/assets/agent-rooms/mira/background.webp
app/static/assets/agent-rooms/mira/avatar.webp
app/static/assets/agent-rooms/mira/foreground.webp
```

After placing the files, open **Customize Room** and set:

```text
/static/assets/agent-rooms/mira/background.webp
/static/assets/agent-rooms/mira/avatar.webp
/static/assets/agent-rooms/mira/foreground.webp
```

Only paths beginning with `/static/` are accepted. Remote arbitrary asset URLs are not stored in Room configuration.

## Layout contract

Room layout is declarative JSON. The default includes:

```json
{
  "scene": "office",
  "avatar_position": {"x": 50, "y": 76, "scale": 1.0},
  "hotspots": [
    {"key": "desk", "label": "Current work", "x": 22, "y": 72},
    {"key": "inbox", "label": "Inbox", "x": 76, "y": 28},
    {"key": "memory", "label": "Notes & memory", "x": 82, "y": 70}
  ]
}
```

No arbitrary JavaScript or expression evaluation is permitted in Room layout.

## Room states

```text
OPEN
FOCUS
AWAY
MAINTENANCE
```

Agent Registry availability remains separate:

```text
AVAILABLE
BUSY
WAITING
OFFLINE
MAINTENANCE
```

Assigning work from a Room changes the Room to `FOCUS`, while actual workload and Agent availability continue to be reconciled by the Registry worker.

## Visitor policy

```text
PRIVATE
DEPARTMENT
TENANT
```

Version `0.16.1` stores the policy for the Room and exposes it in the API. Governance permissions and Tenant isolation remain authoritative. More granular Department visitor enforcement can be added without changing the Room data model.

## Governance

Permissions:

```text
agent-room:read
agent-room:write
agent-room:message
agent-room:assign
```

Execution-controlled actions:

```text
agent-room:write
agent-room:message
agent-room:assign
```

Commercial feature boundaries:

- Room configuration and notes require `registry`
- Direct messages and task assignment require `collaboration`

The existing License, Contract, Tenant, Governance and Kill-Switch layers remain in force.

## Database migration

Alembic head:

```text
20260722_0003
```

Tables:

```text
agent_rooms
agent_room_notes
```

Downgrade is non-destructive because Room notes may contain operational memory. Controlled rollback moves the Alembic marker while preserving Room data.

## UI behavior

The dashboard adds **Agent Rooms** to the sidebar.

Available tabs:

```text
Work Desk
Inbox
Meetings
Notes & Memory
Activity
```

Available actions:

```text
Message
Assign Work
Add Note
Customize
```

Clicking an Agent card in the founding Workforce opens that Agent Room. Double-clicking an Agent in Registry also opens the corresponding Room.

## Deployment

The application starts with:

```text
agent_room_bootstrap:app
```

Required migration:

```bash
alembic -c alembic.ini upgrade head
```

Expected revision:

```text
20260722_0003
```

## Known boundaries

- No browser file uploader is included yet; artwork is deployed through the repository or approved asset pipeline.
- Room Notes do not replace the future organization-wide Memory Control Center.
- Room Inbox does not replace the future human Unified Inbox.
- A Room is not proof that its Runtime is online.
- Custom artwork, customer deployment, signed tag and real Runtime verification remain separate operational evidence.
