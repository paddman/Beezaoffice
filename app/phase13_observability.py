from __future__ import annotations

from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from business_models import IndustryPack, OutcomeRecord, PackInstallation, TenantSubscription
from enterprise_models import EnterpriseTenant
from main import Mission, RuntimeConnector, RuntimeDispatch, app, db_session, engine, redis_client
from protocol_models import ProtocolTask
from registry_models import RegisteredAgent


def remove_route(path: str, method: str) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


remove_route("/api/health", "GET")
remove_route("/metrics", "GET")


@app.get("/metrics", response_class=PlainTextResponse)
def phase13_metrics(db: Session = db_session):
    # FastAPI does not resolve plain generator defaults, so this route is
    # replaced below by a dependency-bound wrapper.
    raise RuntimeError("Dependency wrapper not installed")


remove_route("/metrics", "GET")


from fastapi import Depends  # noqa: E402


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_business_metrics(db: Session = Depends(db_session)) -> str:
    tenants = db.scalar(select(func.count(EnterpriseTenant.id))) or 0
    missions = db.scalar(select(func.count(Mission.id))) or 0
    agents = db.scalar(select(func.count(RegisteredAgent.id))) or 0
    active_dispatches = db.scalar(
        select(func.count(RuntimeDispatch.id)).where(
            RuntimeDispatch.status.in_(["DISPATCHING", "RUNNING", "QUEUED", "WAITING_APPROVAL"])
        )
    ) or 0
    protocol_tasks = db.scalar(select(func.count(ProtocolTask.id))) or 0
    outcomes = db.scalar(select(func.count(OutcomeRecord.id))) or 0
    verified = db.scalar(
        select(func.count(OutcomeRecord.id)).where(OutcomeRecord.status == "VERIFIED")
    ) or 0
    hours_saved = db.scalar(select(func.sum(OutcomeRecord.hours_saved))) or 0.0
    value_created = db.scalar(
        select(func.sum(OutcomeRecord.cost_saved_usd + OutcomeRecord.revenue_value_usd))
    ) or 0.0
    sla_measured = db.scalar(
        select(func.count(OutcomeRecord.id)).where(OutcomeRecord.sla_target_minutes > 0)
    ) or 0
    sla_met = db.scalar(
        select(func.count(OutcomeRecord.id)).where(
            OutcomeRecord.sla_target_minutes > 0,
            OutcomeRecord.sla_met.is_(True),
        )
    ) or 0
    installed_packs = db.scalar(
        select(func.count(PackInstallation.id)).where(PackInstallation.status == "INSTALLED")
    ) or 0
    subscriptions = db.scalar(
        select(func.count(TenantSubscription.id)).where(TenantSubscription.status == "ACTIVE")
    ) or 0
    return "\n".join(
        [
            "# HELP beeza_enterprise_tenants Registered enterprise tenants.",
            "# TYPE beeza_enterprise_tenants gauge",
            f"beeza_enterprise_tenants {tenants}",
            "# HELP beeza_missions_total Durable missions.",
            "# TYPE beeza_missions_total gauge",
            f"beeza_missions_total {missions}",
            "# HELP beeza_registered_agents Registered logical agents.",
            "# TYPE beeza_registered_agents gauge",
            f"beeza_registered_agents {agents}",
            "# HELP beeza_active_runtime_dispatches Active runtime dispatches.",
            "# TYPE beeza_active_runtime_dispatches gauge",
            f"beeza_active_runtime_dispatches {active_dispatches}",
            "# HELP beeza_protocol_tasks_total Protocol gateway tasks.",
            "# TYPE beeza_protocol_tasks_total gauge",
            f"beeza_protocol_tasks_total {protocol_tasks}",
            "# HELP beeza_business_outcomes_total Measured business outcomes.",
            "# TYPE beeza_business_outcomes_total gauge",
            f"beeza_business_outcomes_total {outcomes}",
            "# HELP beeza_business_verified_outcomes Verified business outcomes.",
            "# TYPE beeza_business_verified_outcomes gauge",
            f"beeza_business_verified_outcomes {verified}",
            "# HELP beeza_business_hours_saved Estimated or manually verified hours saved.",
            "# TYPE beeza_business_hours_saved gauge",
            f"beeza_business_hours_saved {float(hours_saved):.4f}",
            "# HELP beeza_business_value_created_usd Cost savings plus attributed revenue value.",
            "# TYPE beeza_business_value_created_usd gauge",
            f"beeza_business_value_created_usd {float(value_created):.4f}",
            "# HELP beeza_business_sla_compliance_ratio SLA compliance for measured outcomes.",
            "# TYPE beeza_business_sla_compliance_ratio gauge",
            f"beeza_business_sla_compliance_ratio {(float(sla_met) / float(sla_measured)) if sla_measured else 0.0:.6f}",
            "# HELP beeza_business_installed_packs Installed industry-pack manifests.",
            "# TYPE beeza_business_installed_packs gauge",
            f"beeza_business_installed_packs {installed_packs}",
            "# HELP beeza_business_active_subscriptions Active tenant subscriptions.",
            "# TYPE beeza_business_active_subscriptions gauge",
            f"beeza_business_active_subscriptions {subscriptions}",
            "",
        ]
    )


@app.get("/api/health")
def phase13_health(db: Session = Depends(db_session)) -> dict[str, object]:
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
    runtimes = list(db.scalars(select(RuntimeConnector).order_by(RuntimeConnector.runtime_key)).all())
    worker = redis_client.hgetall("beezaoffice:business-worker")
    business_worker = worker.get("status", "starting")
    status = "ok" if database == queue == "ok" and business_worker in {"running", "disabled"} else "degraded"
    return {
        "status": status,
        "phase": 13,
        "version": app.version,
        "database": database,
        "queue": queue,
        "business_worker": business_worker,
        "business_last_tick_at": worker.get("last_tick_at"),
        "enterprise_tenants": db.scalar(select(func.count(EnterpriseTenant.id))) or 0,
        "registered_agents": db.scalar(select(func.count(RegisteredAgent.id))) or 0,
        "runtime_connectors": len(runtimes),
        "runtime_online": sum(row.status == "ONLINE" for row in runtimes),
        "runtime_configured": sum(bool(row.base_url) for row in runtimes),
        "business_outcomes": db.scalar(select(func.count(OutcomeRecord.id))) or 0,
        "verified_outcomes": db.scalar(
            select(func.count(OutcomeRecord.id)).where(OutcomeRecord.status == "VERIFIED")
        ) or 0,
        "published_industry_packs": db.scalar(
            select(func.count(IndustryPack.id)).where(IndustryPack.status == "PUBLISHED")
        ) or 0,
        "tenant_isolation": "row-enforced",
        "enterprise_auth": ["platform-token", "oidc-session", "scoped-api-key"],
        "observability": ["health", "readiness", "prometheus", "business-kpi"],
        "governance": "enforced",
        "business_layer": "enabled",
    }
