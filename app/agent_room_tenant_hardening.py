from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import agent_room_app
import agent_room_service
from enterprise_service import DEFAULT_TENANT
from registry_models import RegisteredAgent

_original_agent_for_tenant = agent_room_service.agent_for_tenant
_original_agents_for_tenant = agent_room_service.agents_for_tenant


def hardened_agent_for_tenant(
    db: Session,
    tenant_key: str,
    agent_key: str,
) -> RegisteredAgent | None:
    if tenant_key == DEFAULT_TENANT:
        return db.scalar(
            select(RegisteredAgent).where(RegisteredAgent.agent_key == agent_key)
        )
    return _original_agent_for_tenant(db, tenant_key, agent_key)


def hardened_agents_for_tenant(
    db: Session,
    tenant_key: str,
) -> list[RegisteredAgent]:
    if tenant_key == DEFAULT_TENANT:
        return list(
            db.scalars(
                select(RegisteredAgent).order_by(
                    RegisteredAgent.department_key,
                    RegisteredAgent.display_name,
                )
            ).all()
        )
    return _original_agents_for_tenant(db, tenant_key)


agent_room_service.agent_for_tenant = hardened_agent_for_tenant
agent_room_service.agents_for_tenant = hardened_agents_for_tenant
agent_room_app.agent_for_tenant = hardened_agent_for_tenant
