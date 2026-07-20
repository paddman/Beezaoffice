# Agent Runtime Integrations

BeezaOffice is the command, workforce, and governance plane. OpenClaw, CherryAgent, Hermes Agent, and thClaws remain independent execution runtimes connected through explicit server-side adapters.

## Phase 2 support matrix

| Runtime | Dispatch | Status synchronization | Control |
|---|---|---|---|
| OpenClaw | OpenAI-compatible Gateway endpoint | Synchronous result | Policy remains inside OpenClaw |
| CherryAgent | Native orchestrator run | Poll run snapshot | Status and result synchronization |
| Hermes Agent | Native Runs API | Poll run snapshot | Safe stop, approve once, deny |
| thClaws | Native agent run | Synchronous result | Policy remains inside thClaws |

Runtime credentials remain in the BeezaOffice server environment and are never sent to the browser.

## BeezaOffice environment

```env
OPENCLAW_BASE_URL=http://openclaw-host:18789
OPENCLAW_AUTH_TOKEN=configure-server-side
OPENCLAW_AGENT_TARGET=openclaw/default

CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=configure-server-side

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=configure-server-side

THCLAW_BASE_URL=http://thclaws-host:7878
THCLAW_AUTH_TOKEN=configure-server-side
THCLAW_MODEL=
THCLAW_WORKSPACE_DIR=/var/thcompany/agents/beeza-worker
```

An empty base URL keeps the connector in `UNCONFIGURED` state.

## OpenClaw

Enable the Gateway's OpenAI-compatible chat-completions endpoint and keep it on a private network, loopback interface, or tailnet. BeezaOffice normally targets `openclaw/default`. The shared Gateway credential must be treated as an operator-level credential.

## CherryAgent

BeezaOffice dispatches through the dependency-aware orchestrator and stores the returned run ID. Phase 2 polls the public run snapshot so status changes and final output appear in the BeezaOffice mission timeline. Full event-by-event SSE projection remains a later step.

## Hermes Agent

Enable the Hermes API server and start the Hermes gateway. BeezaOffice uses the stable Runs API for submission, status polling, safe stop, and approval resolution.

The dashboard exposes only two approval choices:

- `once` — permit the current gated action once
- `deny` — reject the current gated action

Session-wide and permanent approvals remain API-only and should be enabled only by an explicit organization policy.

## thClaws

Run thClaws in server mode and configure an absolute workspace directory. Use `THCLAWS_AGENT_WORKSPACE_ROOT` to restrict which workspaces an orchestrator may select. BeezaOffice calls the native agent endpoint so workspace skills remain available.

## BeezaOffice control routes

```text
POST /api/runtimes/{runtime}/dispatch
POST /api/runtime-dispatches/{dispatch}/sync
POST /api/runtime-dispatches/{dispatch}/stop
POST /api/runtime-dispatches/{dispatch}/approval
GET  /api/runtime-dispatches?mission_key=...
```

## Security boundary

- Place each runtime behind a private network or authenticated reverse proxy.
- Use separate credentials for every runtime and rotate them independently.
- BeezaOffice stores bounded output and dispatch metadata, not runtime secrets.
- Runtime tool policies and runtime approval gates remain authoritative.
- Restrict thClaws workspace paths with `THCLAWS_AGENT_WORKSPACE_ROOT`.
- Treat the OpenClaw shared Gateway credential as an operator credential.
- Do not expose session-wide or permanent approval controls in the default UI.
