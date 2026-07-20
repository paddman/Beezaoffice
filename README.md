# BeezaOffice

**AI Workforce Operating System** for operating an organization of 10–1,000 AI agents.

BeezaOffice is not a chatbot collection. It is an operations-first command center where agents can receive missions, join mission rooms, assign work, wait for dependencies, hand work off, follow up, request approval, verify evidence, and report results to humans.

## MVP included

- Command Center dashboard
- 12 founding agents
- Mission queue and live status
- Mission room conversation timeline
- Agent-to-agent handoff and waiting states
- Approval inbox
- Runtime health endpoint
- PostgreSQL and Redis services
- Docker Compose deployment

## Quick deploy

```bash
cp .env.example .env
docker compose -f compose.yml up -d --build
```

Open:

- BeezaOffice: `http://localhost:8080`
- API health: `http://localhost:8080/api/health`
- API docs: `http://localhost:8080/docs`

## Initial architecture

```text
Browser
  -> FastAPI Command Center
      -> PostgreSQL (mission and audit state)
      -> Redis (queue and presence)
      -> Agent runtime adapters (next phase)
```

## Product direction

1. Workforce Kernel
2. Durable Mission Runtime
3. Collaboration Protocol
4. Organization and Chain of Command
5. Scheduler and Runtime Pool
6. Governance and Audit
7. Digital Office UI
8. Scale to 1,000 registered agents

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.
