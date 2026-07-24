# paddman GitHub Portfolio

BeezaOffice connects every repository owned by the GitHub account `paddman` into one governed company portfolio.

The connection does **not** merge repositories, copy source code or change repository permissions. It creates a central portfolio view with an accountable Agent, C-Level sponsor, Department, category and a path to create BeezaOffice Missions from repository work.

## Initial inventory

The version `1.0.0` blueprint contains 23 repositories discovered on 24 July 2026.

| Category | Repositories | Accountable area |
|---|---|---|
| Company control | `Beezaoffice`, `C-level`, `openclawxcherry`, `RABBITAGENT`, `cherryagent`, `cherryteam`, `agent-town-cherry` | Executive, Platform, Operations and Product |
| AI platform | `AIaaS`, `atlas-control-plane`, `CherryFlow`, `mfmas`, `mfmas-memory-for-multi-agent-systems` | AI & Data, Infrastructure and Engineering |
| Developer tools | `cline`, `dev-box-test` | Engineering |
| Products | `-cherry-finance`, `cherrydeskx`, `CherryInsight`, `cherryvoice`, `OmniVoicexcherry` | Finance, Product and AI & Data |
| Product research | `MeuxCompanion` | Product |
| Commercial | `beezashopplan` | Sales |
| Operations | `alertsystem` | Infrastructure |
| Portfolio metadata | `paddman` | Executive Office |

Source of truth:

```text
app/paddman_portfolio_blueprint.py
```

Live connector and API:

```text
app/paddman_portfolio_app.py
```

## Ownership model

Each repository has:

- `accountable_agent` — owns daily delivery and evidence.
- `sponsor_agent` — C-Level sponsor for priority, budget and cross-functional escalation.
- `department` — governed Beeza AI Company Department.
- `category` — portfolio grouping.
- `lifecycle` — initial operating state.

A newly discovered repository is never silently treated as fully classified. Live sync assigns it:

```text
category: unclassified
department: dept:product
accountable_agent: head-product
sponsor_agent: cpo
```

It must then be reviewed and added to the blueprint.

## GitHub token

Configure a fine-grained token in the BeezaOffice environment:

```env
BEEZA_GITHUB_OWNER=paddman
BEEZA_GITHUB_API_URL=https://api.github.com
BEEZA_GITHUB_TOKEN=replace-with-fine-grained-token
```

Minimum recommended repository permissions for live inventory:

```text
Metadata: Read
Contents: Read
```

Grant access to every current and future `paddman` repository when the GitHub token policy permits it. Do not grant Administration, Secrets, Actions write or repository deletion permissions for portfolio synchronization.

The current connector is read-only toward GitHub. It does not create issues, push commits, merge pull requests or change settings.

## API

### Portfolio status

```bash
curl -s http://localhost:8080/api/portfolio/status \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq
```

Important fields:

```text
connected
token_configured
repositories
public
private
archived
unclassified
missing_from_github
synced_at
```

Before the first live sync, BeezaOffice returns the governed 23-repository blueprint with `connected=false`.

### Live GitHub sync

```bash
curl -s -X POST http://localhost:8080/api/portfolio/sync \
  -H "Authorization: Bearer $BEEZA_TOKEN" \
  -H "X-Beeza-Identity: human:owner" | jq
```

Sync performs these steps:

1. Reads all repositories where the authenticated GitHub account is the owner.
2. Filters the result to owner login `paddman`.
3. Merges live metadata with the governed portfolio blueprint.
4. Reports blueprint repositories missing from GitHub.
5. Reports newly discovered unclassified repositories.
6. Stores the latest snapshot in Redis.

A GitHub API failure does not destroy the previous snapshot.

### List and filter repositories

```bash
curl -s 'http://localhost:8080/api/portfolio/repos?category=ai-platform' \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s 'http://localhost:8080/api/portfolio/repos?department=dept:engineering' \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq

curl -s 'http://localhost:8080/api/portfolio/repos?accountable_agent=head-product' \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq
```

### Read one repository

```bash
curl -s http://localhost:8080/api/portfolio/repos/CherryFlow \
  -H "Authorization: Bearer $BEEZA_TOKEN" | jq
```

### Convert repository work into a Mission

```bash
curl -s -X POST http://localhost:8080/api/portfolio/repos/CherryFlow/missions \
  -H "Authorization: Bearer $BEEZA_TOKEN" \
  -H "X-Beeza-Identity: human:owner" \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Ship the first customer-ready CherryFlow workflow",
    "objective": "Select one daily-use workflow, implement it, preserve test evidence and prepare a reversible pilot deployment.",
    "priority": "HIGH"
  }' | jq
```

The Mission receives:

- A unique `REPO-*` Mission key.
- The repository's accountable Agent as commander.
- The repository and sponsor relationship in the Mission event log.
- Initial state `QUEUED`.
- A Rabbit Boss work-breakdown dependency.

Creating a BeezaOffice Mission does not write to the GitHub repository.

## Governance

| Action | Permission |
|---|---|
| Read portfolio | `registry:read` |
| Live GitHub sync | `registry:write` |
| Create repository Mission | `mission:create` |

Money, contracts, personal data, security-impacting changes, destructive changes and production deployment still require the existing human approval gates.

## Verification

```bash
python -m py_compile \
  app/paddman_portfolio_blueprint.py \
  app/paddman_portfolio_app.py

docker build -t beezaoffice:test ./app

docker run --rm \
  -e PYTHONPATH=/srv/beezaoffice \
  -v "$PWD/tests:/tests:ro" \
  beezaoffice:test python /tests/pilot_smoke.py
```

Expected blueprint result:

```json
{
  "repositories": 23,
  "categories": 8,
  "departments": 9
}
```

Live connection is complete only after `POST /api/portfolio/sync` succeeds with the deployment's GitHub token and `/api/portfolio/status` returns `connected=true`.
