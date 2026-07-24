from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import governance_service
from main import Mission, MissionEvent, app, db_session, redis_client, utcnow
from paddman_portfolio_blueprint import (
    PORTFOLIO_COUNTS,
    PORTFOLIO_OWNER,
    PORTFOLIO_VERSION,
    REPOSITORIES,
    repository_map,
)
from phase6_app import require_governance

CACHE_KEY = f"beeza:portfolio:{PORTFOLIO_OWNER}:snapshot"
GITHUB_API_URL = os.getenv("BEEZA_GITHUB_API_URL", "https://api.github.com").rstrip("/")
GITHUB_OWNER = os.getenv("BEEZA_GITHUB_OWNER", PORTFOLIO_OWNER).strip() or PORTFOLIO_OWNER

_PORTFOLIO_RULES = [
    ("POST", re.compile(r"^/api/portfolio/sync$"), "registry:write"),
    ("POST", re.compile(r"^/api/portfolio/repos/[^/]+/missions$"), "mission:create"),
]
for rule in reversed(_PORTFOLIO_RULES):
    if not any(
        existing[0] == rule[0]
        and existing[2] == rule[2]
        and existing[1].pattern == rule[1].pattern
        for existing in governance_service.ROUTE_RULES
    ):
        governance_service.ROUTE_RULES.insert(0, rule)


class PortfolioMissionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=10, max_length=600)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")


def github_token() -> str:
    return (
        os.getenv("BEEZA_GITHUB_TOKEN", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )


def blueprint_snapshot() -> dict[str, Any]:
    repos = [
        {
            **item,
            "connected": False,
            "source": "blueprint",
            "archived": False,
            "fork": False,
            "description": None,
            "language": None,
            "topics": [],
            "open_issues_count": None,
            "updated_at": None,
            "pushed_at": None,
            "size": None,
            "html_url": f"https://github.com/{item['full_name']}",
        }
        for item in REPOSITORIES
    ]
    return {
        "owner": GITHUB_OWNER,
        "portfolio_version": PORTFOLIO_VERSION,
        "source": "blueprint",
        "connected": False,
        "token_configured": bool(github_token()),
        "synced_at": None,
        "counts": PORTFOLIO_COUNTS,
        "repositories": repos,
        "missing_from_github": [],
        "unclassified": [],
    }


def load_snapshot() -> dict[str, Any]:
    try:
        raw = redis_client.get(CACHE_KEY)
    except Exception:
        raw = None
    if not raw:
        return blueprint_snapshot()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return blueprint_snapshot()
    return value if isinstance(value, dict) else blueprint_snapshot()


def save_snapshot(snapshot: dict[str, Any]) -> None:
    redis_client.set(CACHE_KEY, json.dumps(snapshot, ensure_ascii=False, default=str))


def classify_repo(raw: dict[str, Any], blueprint: dict[str, dict[str, Any]]) -> dict[str, Any]:
    name = str(raw.get("name") or "").strip()
    configured = blueprint.get(name)
    if configured is None:
        configured = {
            "name": name,
            "full_name": str(raw.get("full_name") or f"{GITHUB_OWNER}/{name}"),
            "visibility": "private" if raw.get("private") else "public",
            "default_branch": str(raw.get("default_branch") or "main"),
            "category": "unclassified",
            "department": "dept:product",
            "accountable_agent": "head-product",
            "sponsor_agent": "cpo",
            "purpose": "New repository discovered by live GitHub synchronization; classification requires review.",
            "lifecycle": "ACTIVE",
            "classification_source": "live-default",
        }
    return {
        **configured,
        "full_name": str(raw.get("full_name") or configured["full_name"]),
        "visibility": str(raw.get("visibility") or ("private" if raw.get("private") else "public")),
        "default_branch": str(raw.get("default_branch") or configured["default_branch"]),
        "connected": True,
        "source": "github",
        "archived": bool(raw.get("archived")),
        "fork": bool(raw.get("fork")),
        "description": raw.get("description"),
        "language": raw.get("language"),
        "topics": list(raw.get("topics") or []),
        "open_issues_count": raw.get("open_issues_count"),
        "updated_at": raw.get("updated_at"),
        "pushed_at": raw.get("pushed_at"),
        "size": raw.get("size"),
        "html_url": str(raw.get("html_url") or f"https://github.com/{configured['full_name']}"),
    }


async def fetch_owned_repositories() -> list[dict[str, Any]]:
    token = github_token()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Set BEEZA_GITHUB_TOKEN or GITHUB_TOKEN before live portfolio sync",
        )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "BeezaOffice-Paddman-Portfolio/1.0",
    }
    repos: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
        for page in range(1, 11):
            response = await client.get(
                f"{GITHUB_API_URL}/user/repos",
                headers=headers,
                params={
                    "affiliation": "owner",
                    "visibility": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"GitHub portfolio sync failed with HTTP {response.status_code}: {response.text[:500]}",
                )
            body = response.json()
            if not isinstance(body, list):
                raise HTTPException(status_code=502, detail="GitHub returned an invalid repository list")
            owned = [
                item
                for item in body
                if isinstance(item, dict)
                and str((item.get("owner") or {}).get("login") or "").casefold()
                == GITHUB_OWNER.casefold()
            ]
            repos.extend(owned)
            if len(body) < 100:
                break
    return repos


@app.on_event("startup")
def initialize_paddman_portfolio() -> None:
    try:
        if not redis_client.get(CACHE_KEY):
            save_snapshot(blueprint_snapshot())
    except Exception:
        # Redis readiness is handled by the main application startup path.
        return


@app.get("/api/portfolio/status")
def portfolio_status(
    _: str = Depends(require_governance("registry:read")),
) -> dict[str, Any]:
    snapshot = load_snapshot()
    repos = list(snapshot.get("repositories") or [])
    return {
        "owner": snapshot.get("owner", GITHUB_OWNER),
        "portfolio_version": snapshot.get("portfolio_version", PORTFOLIO_VERSION),
        "connected": bool(snapshot.get("connected")),
        "token_configured": bool(github_token()),
        "source": snapshot.get("source"),
        "synced_at": snapshot.get("synced_at"),
        "repositories": len(repos),
        "public": sum(item.get("visibility") == "public" for item in repos),
        "private": sum(item.get("visibility") == "private" for item in repos),
        "archived": sum(bool(item.get("archived")) for item in repos),
        "unclassified": list(snapshot.get("unclassified") or []),
        "missing_from_github": list(snapshot.get("missing_from_github") or []),
        "categories": sorted({str(item.get("category")) for item in repos}),
    }


@app.get("/api/portfolio/repos")
def portfolio_repositories(
    category: str | None = Query(default=None, max_length=100),
    department: str | None = Query(default=None, max_length=100),
    accountable_agent: str | None = Query(default=None, max_length=120),
    _: str = Depends(require_governance("registry:read")),
) -> list[dict[str, Any]]:
    rows = list(load_snapshot().get("repositories") or [])
    if category:
        rows = [row for row in rows if str(row.get("category")) == category]
    if department:
        rows = [row for row in rows if str(row.get("department")) == department]
    if accountable_agent:
        rows = [row for row in rows if str(row.get("accountable_agent")) == accountable_agent]
    return sorted(rows, key=lambda row: str(row.get("name", "")).casefold())


@app.get("/api/portfolio/repos/{repo_name}")
def portfolio_repository(
    repo_name: str,
    _: str = Depends(require_governance("registry:read")),
) -> dict[str, Any]:
    for row in load_snapshot().get("repositories") or []:
        if str(row.get("name", "")).casefold() == repo_name.casefold():
            return row
    raise HTTPException(status_code=404, detail="Portfolio repository not found")


@app.post("/api/portfolio/sync")
async def sync_portfolio(
    actor: str = Depends(require_governance("registry:write")),
) -> dict[str, Any]:
    live = await fetch_owned_repositories()
    blueprint = repository_map()
    rows = [classify_repo(item, blueprint) for item in live]
    live_names = {str(item["name"]) for item in rows}
    expected_names = set(blueprint)
    missing = sorted(expected_names - live_names)
    unclassified = sorted(
        str(item["name"])
        for item in rows
        if item.get("category") == "unclassified"
    )
    snapshot = {
        "owner": GITHUB_OWNER,
        "portfolio_version": PORTFOLIO_VERSION,
        "source": "github",
        "connected": True,
        "token_configured": True,
        "synced_at": utcnow().isoformat(),
        "synced_by": actor,
        "counts": {
            "repositories": len(rows),
            "categories": len({str(item["category"]) for item in rows}),
            "departments": len({str(item["department"]) for item in rows}),
        },
        "repositories": sorted(rows, key=lambda item: str(item["name"]).casefold()),
        "missing_from_github": missing,
        "unclassified": unclassified,
    }
    save_snapshot(snapshot)
    return snapshot


@app.post("/api/portfolio/repos/{repo_name}/missions", status_code=201)
def create_repository_mission(
    repo_name: str,
    payload: PortfolioMissionCreate,
    actor: str = Depends(require_governance("mission:create")),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    repository = None
    for row in load_snapshot().get("repositories") or []:
        if str(row.get("name", "")).casefold() == repo_name.casefold():
            repository = row
            break
    if repository is None:
        raise HTTPException(status_code=404, detail="Portfolio repository not found")

    slug = re.sub(r"[^A-Z0-9]+", "-", repo_name.upper()).strip("-")[:30] or "REPO"
    mission_key = f"REPO-{slug}-{uuid4().hex[:8].upper()}"
    now = utcnow()
    mission = Mission(
        mission_key=mission_key,
        title=payload.title,
        commander=str(repository.get("accountable_agent") or "rabbit-boss"),
        status="QUEUED",
        priority=payload.priority,
        progress=0,
        waiting_for="Rabbit Boss work breakdown and accountable execution plan",
        objective=payload.objective,
        created_at=now,
    )
    db.add(mission)
    db.add(
        MissionEvent(
            mission_key=mission_key,
            actor=actor,
            event_type="PORTFOLIO_REPOSITORY_LINKED",
            message=(
                f"Linked mission to {repository['full_name']}; accountable agent "
                f"{repository['accountable_agent']}, sponsor {repository['sponsor_agent']}."
            ),
            created_at=now,
        )
    )
    db.commit()
    return {
        "mission_key": mission_key,
        "repository": repository,
        "title": mission.title,
        "objective": mission.objective,
        "priority": mission.priority,
        "status": mission.status,
        "commander": mission.commander,
        "created_by": actor,
    }
