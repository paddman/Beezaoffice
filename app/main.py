from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import JSON, DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

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


class MissionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=10, max_length=600)
    priority: str = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")


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
        except Exception as exc:  # startup dependency retry
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Dependencies unavailable: {last_error}")


def seed(db: Session) -> None:
    if db.scalar(select(Agent.id).limit(1)) is not None:
        return

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
        db.add(Agent(agent_key=key, name=name, role=role, department=department, status=status, current_mission=mission, skills=skills))

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
        db.add(MissionEvent(mission_key="INC-2026-0720", actor=actor, event_type=event_type, message=message, created_at=utcnow()))
    db.commit()


app = FastAPI(title="BeezaOffice", version="0.1.0")
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
def health() -> dict[str, Any]:
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
    return {"status": "ok" if database == queue == "ok" else "degraded", "database": database, "queue": queue, "registered_agents": 12}


@app.get("/api/agents")
def list_agents(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Agent).order_by(Agent.department, Agent.name)).all()
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
def list_missions(db: Session = Depends(db_session)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Mission).order_by(Mission.created_at.desc())).all()
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
def mission_detail(mission_key: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    mission = db.scalar(select(Mission).where(Mission.mission_key == mission_key))
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    events = db.scalars(select(MissionEvent).where(MissionEvent.mission_key == mission_key).order_by(MissionEvent.id)).all()
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
            {"actor": event.actor, "type": event.event_type, "message": event.message, "created_at": event.created_at.isoformat()}
            for event in events
        ],
    }


@app.post("/api/missions", dependencies=[Depends(require_token)], status_code=201)
def create_mission(payload: MissionCreate, db: Session = Depends(db_session)) -> dict[str, str]:
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
    db.add(MissionEvent(mission_key=key, actor="Beeza Commander", event_type="MISSION_CREATED", message="Mission accepted and planning started.", created_at=utcnow()))
    db.commit()
    return {"key": key, "status": "PLANNING"}
