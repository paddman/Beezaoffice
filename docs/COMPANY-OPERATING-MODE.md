# Beeza AI Company Operating Mode

BeezaOffice now bootstraps a governed AI company instead of showing only disconnected sample Agents.

## Organization

```text
Human Owner / Shareholders
        ↓
Shareholder Representative
        ↓
Beeza CEO
        ├─ Cherry — Executive Secretary & Chief of Staff
        ├─ CFO → Finance / Procurement
        ├─ COO → Rabbit Boss / Operations / Customer Success
        ├─ CTO → Engineering / Infrastructure / AI & Data
        ├─ CPO → Product
        ├─ CMO → Marketing
        ├─ CRO → Sales
        ├─ CHRO → People Operations
        ├─ CISO → Security Operations
        └─ CLO → Legal Operations
```

Blueprint totals:

- 19 governed Departments
- 26 governed Agents
- 3 initial Missions
- One persistent Agent Room per company Agent
- OpenClaw as the primary Runtime
- DeepSeek V4 Pro for Board, C-Level and high-risk reasoning
- DeepSeek V4 Flash for Department Heads and routine execution

The source of truth is `app/company_blueprint.py`. Database reconciliation and APIs are implemented by `app/company_bootstrap.py`.

## Automatic bootstrap

The production entrypoint imports `company_bootstrap`. Startup performs an idempotent reconciliation:

1. Create or update the Department hierarchy.
2. Create Governance identities and Role Bindings.
3. Register the 26 company Agents.
4. Create legacy Agent records for existing dashboard compatibility.
5. Create an Agent Room for every company Agent.
6. Create controlled delegation links.
7. Create the initial company Missions.

Existing workload counters, reliability history and completed work are preserved. Structural organization fields are reconciled to the current blueprint.

Disable automatic bootstrap only when a deployment supplies its own organization:

```env
BEEZA_COMPANY_BOOTSTRAP_ENABLED=false
```

## Start locally

```bash
cp .env.example .env
# Set passwords and tokens in .env.

docker compose -f compose.yml up -d --build --force-recreate
docker compose -f compose.yml ps
docker compose -f compose.yml logs -f beezaoffice
```

## Verify the company

```bash
export BEEZA_TOKEN='value-of-BEEZA_AUTH_TOKEN'

curl -s http://localhost:8080/api/company/status \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s http://localhost:8080/api/company/charter \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s http://localhost:8080/api/company/agents \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s http://localhost:8080/api/registry/organization \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s http://localhost:8080/api/agent-rooms \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq
```

A healthy `/api/company/status` response has:

```json
{
  "operational": true,
  "counts": {
    "departments": 19,
    "agents": 26,
    "missions": 3,
    "registered_agents": 26,
    "agent_rooms_ready": 26
  },
  "missing": {
    "agents": [],
    "departments": [],
    "missions": [],
    "agent_rooms": []
  }
}
```

## Manual reconciliation

Startup normally handles reconciliation. The owner can run it manually after changing the blueprint:

```bash
curl -s -X POST http://localhost:8080/api/company/reconcile \
  -H "Authorization: Bearer $BEEZA_TOKEN" \
  -H "X-Beeza-Identity: human:owner" | jq
```

This endpoint is intentionally owner-level because it changes governed organization structure.

## OpenClaw connection

Configure the OpenClaw Gateway OpenAI-compatible endpoint:

```env
OPENCLAW_BASE_URL=http://openclaw-gateway:18789
OPENCLAW_AUTH_TOKEN=replace-with-gateway-token
OPENCLAW_AGENT_TARGET=openclaw/default
```

Then probe the Runtime:

```bash
curl -s -X POST http://localhost:8080/api/runtimes/openclaw/probe \
  -H "Authorization: Bearer $BEEZA_TOKEN" \
  -H "X-Beeza-Identity: human:owner" | jq
```

The Company Blueprint records preferred model labels:

```text
Board / C-Level / Cherry high-risk escalation / Rabbit Boss
  deepseek/deepseek-v4-pro

Department Heads
  deepseek/deepseek-v4-flash
```

Actual model availability remains controlled by the connected OpenClaw deployment.

## Initial Missions

### `COMPANY-LAUNCH-001`

Commander: Rabbit Boss

Goal: activate operating rhythm, verify escalation gates and publish the first executive scorecard within seven days.

### `PILOT-FIRST-CUSTOMER-001`

Commander: Beeza CRO

Goal: choose one painful workflow, define acceptance gates, deploy a governed OpenClaw pilot and obtain named human acceptance within thirty days.

### `EXEC-DAILY-BRIEF-001`

Commander: Cherry

Goal: publish a daily brief covering revenue, product, delivery, incidents, approvals, blockers and next accountable actions.

## First-day operating rhythm

### Morning — Cherry

- Read open Missions, approvals and incidents.
- Produce one executive brief.
- Route operational work to Rabbit Boss.
- Route strategic, financial, legal or security decisions to the relevant C-Level Agent.

### Execution — Rabbit Boss

- Break each accepted outcome into workstreams.
- Assign one accountable owner per action.
- Set deadline, KPI, dependency, evidence and rollback.
- Escalate when cost, scope, security, legal, personal data or production impact exceeds authority.

### Department Heads

- Own daily queues and SLA.
- Execute approved work through OpenClaw.
- Preserve evidence and update Mission progress.
- Escalate exceptions to the sponsoring C-Level Agent.

### C-Level

- Set policy, budget and risk boundaries.
- Resolve cross-functional trade-offs.
- Do not replace Department Heads in daily execution.

### Human Owner

Human approval remains mandatory for:

- Equity and shareholder resolutions
- Money transfer and material spend
- Contract signature and regulatory filing
- Personal-data access or export
- Destructive action and production change
- Final claims of legal, security or regulatory compliance

## Change control

Changes to company structure should follow this order:

1. Edit `app/company_blueprint.py`.
2. Run the Pilot smoke test.
3. Deploy to a non-production environment.
4. Call `/api/company/reconcile` as `human:owner`.
5. Verify `/api/company/status` and `/api/registry/organization`.
6. Review Agent Rooms and active delegations.
7. Promote only after Pilot gates pass.
