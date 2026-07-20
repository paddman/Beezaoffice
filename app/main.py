from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from runtime_adapters import (
    RuntimeAdapterError,
    RuntimeConfig,
    dispatch_runtime,
    probe_runtime,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://beeza:change-this-password@postgres:5432/beezaoffice",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
AUTH_TOKEN = os.getenv("BEEZA_AUTH_TOKEN", "")
STATIC_DIR = Path(__file__).parent / "static"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(140))
    department: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE")
    current_mission: Mapped[str | None] = mapped_column(String(160), nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    commander: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(40))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    waiting_for: Mapped[str | None] = mapped_column(String(180), nullable=True)
    objective: Mapped[str] = mapped_column(String(600))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MissionEvent(Base):
    __tablename__ = "mission_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(String(800))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuntimeConnector(Base):
    __tablename__ = "runtime_connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    runtime_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(60))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    transport: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="UNCONFIGURED")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(160), default="")
    agent_target: Mapped[str] = mapped_column(String(160), default="")
    workspace_dir: Mapped[str] = mapped_column(String(500), default="")
    auth_env: Mapped[str] = mapped_column(String(120))
    last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(800), nullable=True)


class RuntimeDispatch(Base):
    __tablename__ = "runtime_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispatch_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    runtime_key: Mapped[str] = mapped_column(String(80), index=True)
    mission_key: Mapped[str] = mapped_column(String(80), index=True)
    remote_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    status: Mapped[str] = mapped_column(String(60), default="DISPATCHING")
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MissionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=10, max_length=600)
    priority: str = Field(
        default="NORMAL",
        pattern="^(LOW|NORMAL|HIGH|CRITICAL)$",
    )


class RuntimeDispatchCreate(BaseModel):
    mission_key: str = Field(min_length=3, max_length=80)
    prompt: str | None = Field(default=None, max_length=8000)
    roles: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=30)
    instructions: str | None = Field(default=None, max_length=3000)


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not AUTH_TOKEN:
        return
    if authorization != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid BeezaOffice token")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def wait_for_services() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            Base.metadata.create_all(engine)
            redis_client.ping()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Dependencies unavailable: {last_error}")


def runtime_specs() -> list[dict[str, Any]]:
    return [
        {
            "key": "openclaw",
            "display_name": "OpenClaw",
            "platform": "openclaw",
            "base_url": os.getenv("OPENCLAW_BASE_URL", "").strip(),
            "transport": "Gateway OpenAI-compatible HTTP",
            "capabilities": [
                "Gateway",
                "agent routing",
                "channels",
                "skills",
                "tool execution",
            ],
            "model": "",
            "agent_target": os.getenv(
                "OPENCLAW_AGENT_TARGET",
                "openclaw/default",
            ).strip(),
            "workspace_dir": "",
            "auth_env": "OPENCLAW_AUTH_TOKEN",
        },
        {
            "key": "cherryagent",
            "display_name": "CherryAgent",
            "platform": "cherryagent",
            "base_url": os.getenv("CHERRYAGENT_BASE_URL", "").strip(),
            "transport": "Native Orchestrator Runs API",
            "capabilities": [
                "orchestrator runs",
                "engineer loop",
                "approvals",
                "SSE",
                "runbooks",
            ],
            "model": "",
            "agent_target": "",
            "workspace_dir": "",
            "auth_env": "CHERRYAGENT_AUTH_TOKEN",
        },
        {
            "key": "hermes",
            "display_name": "Hermes Agent",
            "platform": "hermes",
            "base_url": os.getenv("HERMES_BASE_URL", "").strip(),
            "transport": "Runs API + SSE",
            "capabilities": [
                "runs API",
                "subagents",
                "skills",
                "memory",
                "scheduled work",
            ],
            "model": os.getenv("HERMES_MODEL", "hermes-agent").strip(),
            "agent_target": "",
            "workspace_dir": "",
            "auth_env": "HERMES_AUTH_TOKEN",
        },
        {
            "key": "thclaws",
            "display_name": "thClaws",
            "platform": "thclaws",
            "base_url": os.getenv("THCLAW_BASE_URL", "").strip(),
            "transport": "Native /agent/run API",
            "capabilities": [
                "agent/run",
                "workspace skills",
                "MCP",
                "agent teams",
                "local models",
            ],
            "model": os.getenv("THCLAW_MODEL", "").strip(),
            "agent_target": "",
            "workspace_dir": os.getenv("THCLAW_WORKSPACE_DIR", "").strip(),
            "auth_env": "THCLAW_AUTH_TOKEN",
        },
    ]


def seed_runtimes(db: Session) -> None:
    for spec in runtime_specs():
        row = db.scalar(
            select(RuntimeConnector).where(
                RuntimeConnector.runtime_key == spec["key"]
            )
        )
        configured = bool(spec["base_url"])
        if row is None:
            row = RuntimeConnector(
                runtime_key=spec["key"],
                display_name=spec["display_name"],
                platform=spec["platform"],
                base_url=spec["base_url"],
                transport=spec["transport"],
                status="UNKNOWN" if configured else "UNCONFIGURED",
                capabilities=spec["capabilities"],
                model=spec["model"],
                agent_target=spec["agent_target"],
                workspace_dir=spec["workspace_dir"],
                auth_env=spec["auth_env"],
            )
            db.add(row)
            continue

        previous_url = row.base_url
        row.display_name = spec["display_name"]
        row.platform = spec["platform"]
        row.base_url = spec["base_url"]
        row.transport = spec["transport"]
        row.capabilities = spec["capabilities"]
        row.model = spec["model"]
        row.agent_target = spec["agent_target"]
        row.workspace_dir = spec["workspace_dir"]
        row.auth_env = spec["auth_env"]
        if not configured:
            row.status = "UNCONFIGURED"
            row.last_error = None
        elif previous_url != row.base_url or row.status == "UNCONFIGURED":
            row.status = "UNKNOWN"
            row.last_error = None
    db.commit()


def seed(db: Session) -> None:
    if db.scalar(select(Agent.id).limit(1)) is None:
        agents = [
            ("rei", "Rei", "Incident Commander", "Operations", "RUNNING", "INC-2026-0720", ["triage", "coordination", "escalation"]),
            ("aiden", "Aiden", "Infrastructure Operator", "Operations", "RUNNING", "INC-2026-0720", ["linux", "proxmox", "storage"]),
            ("noah", "Noah", "Data & Capacity Analyst", "Data", "WAITING", "INC-2026-0720", ["metrics", "forecasting", "sql"]),
            ("yuna", "Yuna", "QA & Evidence Verifier", "Quality", "WAITING", "INC-2026-0720", ["verification", "evidence", "policy"]),
            ("mira", "Mira", "Executive Secretary", "Executive", "AVAILABLE", None, ["briefing", "reporting", "calendar"]),
            ("leon", "Leon", "Chief Financial Officer", "Finance", "AVAILABLE", None, ["budget", "forecast", "risk"]),
            ("irene", "Irene", "Accounting Specialist", "Finance", "AVAILABLE", None, ["invoice", "ledger", "tax"]),
            ("luna", "Luna", "Customer Support Lead", "Support", "AVAILABLE", None, ["ticketing", "escalation", "customer-care"]),
            ("claire", "Claire", "Human Resources Lead", "People", "AVAILABLE", None, ["hiring", "performance", "policy"]),
            ("selene", "Selene", "Legal & Compliance", "Legal", "AVAILABLE", None, ["contracts", "compliance", "privacy"]),
            ("kai", "Kai", "Procurement Specialist", "Procurement", "AVAILABLE", None, ["vendor", "purchase-order", "sourcing"]),
            ("aria", "Aria", "Marketing Strategist", "Marketing", "AVAILABLE", None, ["campaign", "content", "analytics"]),
        ]
        for key, name, role, department, status, mission, skills in agents:
            db.add(
                Agent(
                    agent_key=key,
                    name=name,
                    role=role,
                    department=department,
                    status=status,
                    current_mission=mission,
                    skills=skills,
                )
            )

        missions = [
            Mission(
                mission_key="INC-2026-0720",
                title="Storage latency investigation",
                commander="Rei",
                status="EXECUTING",
                priority="CRITICAL",
                progress=64,
                waiting_for="Noah waiting for Aiden metrics package",
                objective="Identify root cause, propose a safe remediation, obtain approval, verify recovery and produce an incident report.",
                created_at=utcnow(),
            ),
            Mission(
                mission_key="OPS-DAILY-042",
                title="Executive daily operations brief",
                commander="Mira",
                status="QUEUED",
                priority="NORMAL",
                progress=12,
                waiting_for="Waiting for incident summary",
                objective="Create a verified daily brief covering operational health, risk, approvals and open missions.",
                created_at=utcnow(),
            ),
            Mission(
                mission_key="FIN-APR-018",
                title="Cloud capacity budget review",
                commander="Leon",
                status="WAITING_APPROVAL",
                priority="HIGH",
                progress=82,
                waiting_for="Human budget approval",
                objective="Validate forecast, compare vendor options and prepare an approval-ready recommendation.",
                created_at=utcnow(),
            ),
        ]
        db.add_all(missions)

        timeline = [
            ("Rei", "MEETING_STARTED", "Opened mission room and assigned investigation tracks."),
            ("Aiden", "TASK_ACCEPTED", "Accepted infrastructure diagnostics work package."),
            ("Noah", "WAITING_DATA", "Waiting for Prometheus metrics and multipath evidence from Aiden."),
            ("Aiden", "HANDOFF", "Uploaded latency metrics and storage-path evidence for Noah."),
            ("Noah", "ANALYSIS_RUNNING", "Correlation analysis started; queue depth is the leading hypothesis."),
            ("Yuna", "REVIEW_QUEUED", "Evidence review queued after analysis completion."),
        ]
        for actor, event_type, message in timeline:
            db.add(
                MissionEvent(
                    mission_key="INC-2026-0720",
                    actor=actor,
                    event_type=event_type,
                    message=message,
                    created_at=utcnow(),
                )
            )
        db.commit()

    seed_runtimes(db)


def runtime_config(row: RuntimeConnector) -> RuntimeConfig:
    return RuntimeConfig(
        key=row.runtime_key,
        platform=row.platform,
        base_url=row.base_url,
        auth_token=os.getenv(row.auth_env, "").strip(),
        model=row.model,
        agent_target=row.agent_target,
        workspace_dir=row.workspace_dir,
    )


def runtime_view(row: RuntimeConnector) -> dict[str, Any]:
    return {
        "key": row.runtime_key,
        "name": row.display_name,
        "platform": row.platform,
        "base_url": row.base_url,
        "configured": bool(row.base_url),
        "auth_configured": bool(os.getenv(row.auth_env, "").strip()),
        "transport": row.transport,
        "status": row.status,
        "capabilities": row.capabilities,
        "model": row.model,
        "agent_target": row.agent_target,
        "workspace_configured": bool(row.workspace_dir),
        "last_probe_at": (
            row.last_probe_at.isoformat() if row.last_probe_at else None
        ),
        "last_latency_ms": row.last_latency_ms,
        "last_error": row.last_error,
    }


def bounded_payload(value: Any, max_chars: int = 12000) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        encoded = str(value)
    if len(encoded) <= max_chars:
        return value
    return {
        "truncated": True,
        "preview": encoded[:max_chars],
        "original_chars": len(encoded),
    }


def dispatch_view(row: RuntimeDispatch) -> dict[str, Any]:
    return {
        "key": row.dispatch_key,
        "runtime_key": row.runtime_key,
        "mission_key": row.mission_key,
        "remote_id": row.remote_id,
        "status": row.status,
        "output": row.output,
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


app = FastAPI(title="BeezaOffice", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    wait_for_services()
    with SessionLocal() as db:
        seed(db)
    redis_client.set("beezaoffice:runtime", "online")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health(db: Session = Depends(db_session)) -> dict[str, Any]:
    database = "ok"
    queue = "ok"
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception:
        database = "error"
    try:
        redis_client.ping()
    except Exception:
        queue = "error"

    runtimes = db.scalars(
        select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)
    ).all()
    return {
        "status": "ok" if database == queue == "ok" else "degraded",
        "database": database,
        "queue": queue,
        "registered_agents": 12,
        "runtime_connectors": len(runtimes),
        "runtime_online": sum(row.status == "ONLINE" for row in runtimes),
        "runtime_configured": sum(bool(row.base_url) for row in runtimes),
    }


@app.get("/api/agents")
def list_agents(
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Agent).order_by(Agent.department, Agent.name)
    ).all()
    return [
        {
            "key": row.agent_key,
            "name": row.name,
            "role": row.role,
            "department": row.department,
            "status": row.status,
            "current_mission": row.current_mission,
            "skills": row.skills,
        }
        for row in rows
    ]


@app.get("/api/missions")
def list_missions(
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Mission).order_by(Mission.created_at.desc())
    ).all()
    return [
        {
            "key": row.mission_key,
            "title": row.title,
            "commander": row.commander,
            "status": row.status,
            "priority": row.priority,
            "progress": row.progress,
            "waiting_for": row.waiting_for,
            "objective": row.objective,
        }
        for row in rows
    ]


@app.get("/api/missions/{mission_key}")
def mission_detail(
    mission_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == mission_key)
    )
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    events = db.scalars(
        select(MissionEvent)
        .where(MissionEvent.mission_key == mission_key)
        .order_by(MissionEvent.id)
    ).all()
    return {
        "key": mission.mission_key,
        "title": mission.title,
        "commander": mission.commander,
        "status": mission.status,
        "priority": mission.priority,
        "progress": mission.progress,
        "waiting_for": mission.waiting_for,
        "objective": mission.objective,
        "events": [
            {
                "actor": event.actor,
                "type": event.event_type,
                "message": event.message,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
    }


@app.post(
    "/api/missions",
    dependencies=[Depends(require_token)],
    status_code=201,
)
def create_mission(
    payload: MissionCreate,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    sequence = int(redis_client.incr("beezaoffice:mission-sequence"))
    key = f"MISSION-{utcnow():%Y%m%d}-{sequence:04d}"
    mission = Mission(
        mission_key=key,
        title=payload.title,
        commander="Beeza Commander",
        status="PLANNING",
        priority=payload.priority,
        progress=5,
        waiting_for="Dynamic team formation",
        objective=payload.objective,
        created_at=utcnow(),
    )
    db.add(mission)
    db.add(
        MissionEvent(
            mission_key=key,
            actor="Beeza Commander",
            event_type="MISSION_CREATED",
            message="Mission accepted and planning started.",
            created_at=utcnow(),
        )
    )
    db.commit()
    return {"key": key, "status": "PLANNING"}


@app.get("/api/runtimes")
def list_runtimes(
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RuntimeConnector).order_by(RuntimeConnector.id)
    ).all()
    return [runtime_view(row) for row in rows]


@app.post(
    "/api/runtimes/{runtime_key}/probe",
    dependencies=[Depends(require_token)],
)
async def probe_agent_runtime(
    runtime_key: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.scalar(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key == runtime_key
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Runtime not found")

    try:
        result = await probe_runtime(runtime_config(row))
        row.status = str(result["status"])
        row.last_latency_ms = result.get("latency_ms")
        row.last_error = None
    except RuntimeAdapterError as exc:
        row.status = "OFFLINE"
        row.last_latency_ms = None
        row.last_error = str(exc)[:800]
    row.last_probe_at = utcnow()
    db.commit()
    db.refresh(row)
    return runtime_view(row)


@app.post(
    "/api/runtimes/{runtime_key}/dispatch",
    dependencies=[Depends(require_token)],
    status_code=202,
)
async def dispatch_to_agent_runtime(
    runtime_key: str,
    payload: RuntimeDispatchCreate,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    runtime = db.scalar(
        select(RuntimeConnector).where(
            RuntimeConnector.runtime_key == runtime_key
        )
    )
    if not runtime:
        raise HTTPException(status_code=404, detail="Runtime not found")
    mission = db.scalar(
        select(Mission).where(Mission.mission_key == payload.mission_key)
    )
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    now = utcnow()
    dispatch = RuntimeDispatch(
        dispatch_key=f"DSP-{uuid4().hex[:12].upper()}",
        runtime_key=runtime.runtime_key,
        mission_key=mission.mission_key,
        status="DISPATCHING",
        output={},
        created_at=now,
        updated_at=now,
    )
    db.add(dispatch)
    db.commit()
    db.refresh(dispatch)

    work_package = {
        "mission_key": mission.mission_key,
        "title": mission.title,
        "objective": mission.objective,
        "priority": mission.priority,
        "prompt": payload.prompt,
        "roles": payload.roles,
        "tags": payload.tags,
        "instructions": payload.instructions,
    }

    try:
        result = await dispatch_runtime(
            runtime_config(runtime),
            work_package,
        )
        dispatch.remote_id = (
            str(result["remote_id"]) if result.get("remote_id") else None
        )
        dispatch.status = str(result.get("status") or "STARTED")
        dispatch.output = {
            "summary": str(result.get("output") or "")[:5000],
            "latency_ms": result.get("latency_ms"),
            "remote": bounded_payload(result.get("raw") or {}),
        }
        dispatch.updated_at = utcnow()
        runtime.status = "ONLINE"
        runtime.last_latency_ms = result.get("latency_ms")
        runtime.last_error = None
        runtime.last_probe_at = utcnow()

        if dispatch.status == "COMPLETED":
            mission.waiting_for = (
                f"{runtime.display_name} result received; awaiting Beeza review"
            )
        else:
            suffix = f" {dispatch.remote_id}" if dispatch.remote_id else ""
            mission.waiting_for = (
                f"Waiting for {runtime.display_name} run{suffix}"
            )
        mission.progress = max(mission.progress, 10)
        db.add(
            MissionEvent(
                mission_key=mission.mission_key,
                actor="Beeza Commander",
                event_type="RUNTIME_DISPATCHED",
                message=(
                    f"Sent work package to {runtime.display_name} through "
                    f"{runtime.transport}. Dispatch {dispatch.dispatch_key}; "
                    f"remote status {dispatch.status}."
                ),
                created_at=utcnow(),
            )
        )
        db.commit()
        db.refresh(dispatch)
        return dispatch_view(dispatch)
    except RuntimeAdapterError as exc:
        dispatch.status = "FAILED"
        dispatch.error = str(exc)[:1200]
        dispatch.updated_at = utcnow()
        runtime.status = "OFFLINE"
        runtime.last_error = str(exc)[:800]
        runtime.last_probe_at = utcnow()
        db.add(
            MissionEvent(
                mission_key=mission.mission_key,
                actor="Beeza Commander",
                event_type="RUNTIME_DISPATCH_FAILED",
                message=(
                    f"{runtime.display_name} rejected or could not receive "
                    f"dispatch {dispatch.dispatch_key}: {str(exc)[:500]}"
                ),
                created_at=utcnow(),
            )
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/runtime-dispatches")
def list_runtime_dispatches(
    mission_key: str | None = None,
    db: Session = Depends(db_session),
) -> list[dict[str, Any]]:
    statement = select(RuntimeDispatch)
    if mission_key:
        statement = statement.where(
            RuntimeDispatch.mission_key == mission_key
        )
    rows = db.scalars(
        statement.order_by(RuntimeDispatch.created_at.desc()).limit(100)
    ).all()
    return [dispatch_view(row) for row in rows]
