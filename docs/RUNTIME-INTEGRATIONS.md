# Agent Runtime Integrations

BeezaOffice is the command, workforce, and governance plane. OpenClaw, CherryAgent, Hermes Agent, and thClaws remain independent execution runtimes connected through explicit adapters.

## Supported runtimes

| Runtime | BeezaOffice adapter | Dispatch endpoint | Progress model |
|---|---|---|---|
| OpenClaw | Gateway OpenAI-compatible HTTP | `POST /v1/chat/completions` | Synchronous result; Gateway sessions remain available |
| CherryAgent | Native orchestrator | `POST /orchestrator/runs` | Remote run ID and CherryAgent SSE topology |
| Hermes Agent | Native Runs API | `POST /v1/runs` | Poll/SSE/stop/approval on Hermes |
| thClaws | Native orchestrator | `POST /agent/run` | Sync result now; native SSE/callback can be added later |

BeezaOffice never copies runtime credentials into the browser. Base URLs and bearer tokens are read from server environment variables.

## Configure BeezaOffice

Copy `.env.example` to `.env`, then set only the runtimes being used:

```env
OPENCLAW_BASE_URL=http://openclaw-host:18789
OPENCLAW_AUTH_TOKEN=replace-me
OPENCLAW_AGENT_TARGET=openclaw/default

CHERRYAGENT_BASE_URL=http://cherryagent-host:8787
CHERRYAGENT_AUTH_TOKEN=replace-me

HERMES_BASE_URL=http://hermes-host:8642
HERMES_AUTH_TOKEN=replace-me

THCLAW_BASE_URL=http://thclaws-host:7878
THCLAW_AUTH_TOKEN=replace-me
THCLAW_MODEL=
THCLAW_WORKSPACE_DIR=/var/thcompany/agents/beeza-worker
```

An empty base URL keeps that connector in `UNCONFIGURED` state.

## OpenClaw

OpenClaw's OpenAI-compatible HTTP surface is disabled by default. Enable it in the Gateway configuration:

```json5
{
  gateway: {
    http: {
      endpoints: {
        chatCompletions: { enabled: true }
      }
    }
  }
}
```

BeezaOffice sends the mission to the configured agent target, normally `openclaw/default`. Keep the Gateway on loopback, a private network, or a tailnet; its shared bearer credential is an operator-level credential.

Probe:

```bash
curl -H "Authorization: Bearer $OPENCLAW_AUTH_TOKEN" \
  "$OPENCLAW_BASE_URL/v1/models"
```

## CherryAgent

Start CherryAgent and authenticate BeezaOffice with a CherryAgent bearer session/token. BeezaOffice uses the dependency-aware orchestrator API rather than `/chat`:

```bash
curl -X POST "$CHERRYAGENT_BASE_URL/orchestrator/runs" \
  -H "Authorization: Bearer $CHERRYAGENT_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal":"Verify the service health and return evidence","tags":["beezaoffice"]}'
```

CherryAgent keeps the remote task topology, logs, evidence, and SSE event stream. BeezaOffice stores the returned run ID on the mission dispatch record.

## Hermes Agent

Enable Hermes' API server:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=replace-me
```

Run:

```bash
hermes gateway
```

BeezaOffice submits long-form work through `POST /v1/runs`. Hermes retains its own tool progress, approval, stop, and SSE endpoints.

Probe:

```bash
curl -H "Authorization: Bearer $HERMES_AUTH_TOKEN" \
  "$HERMES_BASE_URL/health"
```

## thClaws

Run thClaws as a server with bearer authentication:

```bash
THCLAWS_API_TOKEN=replace-me \
thclaws --serve --bind 0.0.0.0 --port 7878
```

BeezaOffice uses the native `POST /agent/run` contract so thClaws can load workspace skills and run as an agent peer instead of being treated as a raw model.

For workspace isolation:

```bash
export THCLAWS_AGENT_WORKSPACE_ROOT=/var/thcompany/agents
```

Then set `THCLAW_WORKSPACE_DIR` to an absolute child directory visible to the thClaws process.

## BeezaOffice API

List connectors:

```bash
curl http://localhost:8080/api/runtimes
```

Probe one connector:

```bash
curl -X POST http://localhost:8080/api/runtimes/openclaw/probe \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN"
```

Dispatch the selected BeezaOffice mission:

```bash
curl -X POST http://localhost:8080/api/runtimes/hermes/dispatch \
  -H "Authorization: Bearer $BEEZA_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mission_key":"INC-2026-0720","tags":["incident","critical"]}'
```

Inspect dispatch history:

```bash
curl "http://localhost:8080/api/runtime-dispatches?mission_key=INC-2026-0720"
```

## Security boundary

- Put every runtime on a private network or authenticated reverse proxy.
- Use separate credentials per runtime and rotate them independently.
- BeezaOffice records dispatch metadata and bounded output, not runtime secrets.
- Runtime tool policies and approval gates remain authoritative.
- thClaws workspace paths should be restricted with `THCLAWS_AGENT_WORKSPACE_ROOT`.
- OpenClaw's shared HTTP bearer token must be treated as an operator credential.
