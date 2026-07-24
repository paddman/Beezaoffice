from __future__ import annotations

from agent_room_bootstrap import app
from agent_room_models import AgentRoom, AgentRoomNote
from commercial_models import (
    BrandProfile,
    CommercialLicense,
    DeploymentActivation,
    FeatureEntitlement,
    ReleaseManifest,
    TenantOnboarding,
)
from commercial_quota_hardening import commercial_feature_for_request
from company_blueprint import BLUEPRINT_COUNTS, COMPANY_CHARTER, validate_blueprint
from governance_service import EXECUTION_ACTIONS, permission_for_request
from paddman_portfolio_blueprint import PORTFOLIO_COUNTS, PORTFOLIO_OWNER, validate_portfolio
from phase14_app import feature_for_request
from phase14_release import ReleasePublish
from phase14_schema import migration_aware_readiness
from pilot_app import PILOT_GATES
from pilot_models import PilotGateEvidence, PilotProgram
from pilot_service import DEFAULT_ACCEPTANCE_CRITERIA, evidence_hash
from release_version import APP_VERSION, RELEASE_CHANNEL, RELEASE_TAG
from schema_service import expected_revision, schema_status


def run() -> None:
    paths = [getattr(route, "path", None) for route in app.router.routes]
    constraint = next(
        item
        for item in FeatureEntitlement.__table__.constraints
        if item.name == "uq_commercial_tenant_feature_source"
    )
    release = ReleasePublish(
        version=APP_VERSION,
        image_ref=f"ghcr.io/paddman/beezaoffice:{APP_VERSION}",
        image_digest="sha256:" + "a" * 64,
        signature_ref="oci://signature",
        sbom_ref="oci://sbom",
        provenance_ref="oci://provenance",
    )

    assert APP_VERSION == "0.16.1"
    assert RELEASE_TAG == "v0.16.1"
    assert RELEASE_CHANNEL == "pilot"
    assert app.version == APP_VERSION
    assert expected_revision() == "20260722_0003"
    assert callable(schema_status) and callable(migration_aware_readiness)

    assert validate_blueprint() == BLUEPRINT_COUNTS
    assert BLUEPRINT_COUNTS == {"departments": 19, "agents": 26, "missions": 3}
    assert COMPANY_CHARTER["name"] == "Beeza AI Company"
    assert COMPANY_CHARTER["operating_system"] == "BeezaOffice"

    assert validate_portfolio() == PORTFOLIO_COUNTS
    assert PORTFOLIO_OWNER == "paddman"
    assert PORTFOLIO_COUNTS == {"repositories": 23, "categories": 8, "departments": 9}

    assert TenantOnboarding.__tablename__ == "commercial_onboarding"
    assert CommercialLicense.__tablename__ == "commercial_licenses"
    assert FeatureEntitlement.__tablename__ == "commercial_feature_entitlements"
    assert BrandProfile.__tablename__ == "commercial_brand_profiles"
    assert DeploymentActivation.__tablename__ == "commercial_deployments"
    assert ReleaseManifest.__tablename__ == "commercial_release_manifests"
    assert PilotProgram.__tablename__ == "pilot_programs"
    assert PilotGateEvidence.__tablename__ == "pilot_gate_evidence"
    assert AgentRoom.__tablename__ == "agent_rooms"
    assert AgentRoomNote.__tablename__ == "agent_room_notes"
    assert [column.name for column in constraint.columns] == [
        "tenant_key",
        "feature_key",
        "source",
    ]

    assert len(PILOT_GATES) == 10
    assert "runtime_e2e" in PILOT_GATES
    assert "customer_acceptance" in PILOT_GATES
    assert DEFAULT_ACCEPTANCE_CRITERIA["minimum_security_score"] == 90
    assert len(evidence_hash({"pilot": "test"})) == 64
    assert release.channel == "stable"

    assert feature_for_request("POST", "/api/missions") == "core.missions"
    assert feature_for_request("POST", "/message:send") == "protocol"
    assert feature_for_request("POST", "/api/enterprise/tenants") == "enterprise"
    assert commercial_feature_for_request("POST", "/api/enterprise/tenants") == "enterprise"
    assert feature_for_request("POST", "/api/agent-rooms/mira/tasks") == "collaboration"
    assert feature_for_request("POST", "/api/agent-rooms/mira/messages") == "collaboration"
    assert feature_for_request("POST", "/api/agent-rooms/mira/notes") == "registry"
    assert feature_for_request("PATCH", "/api/agent-rooms/mira") == "registry"
    assert feature_for_request("GET", "/api/missions") is None
    assert feature_for_request("GET", "/api/company/status") is None
    assert feature_for_request("GET", "/api/portfolio/status") is None

    required_paths = {
        "/api/commercial/status": 1,
        "/api/commercial/license/import": 1,
        "/api/commercial/brand": 2,
        "/api/commercial/deployments": 2,
        "/api/commercial/releases": 1,
        "/api/commercial/releases/publish": 1,
        "/api/pilot/checklist": 1,
        "/api/pilot/status": 1,
        "/api/pilot/programs": 2,
        "/api/pilot/programs/{pilot_key}": 1,
        "/api/pilot/programs/{pilot_key}/gates": 1,
        "/api/pilot/programs/{pilot_key}/decision": 1,
        "/api/agent-rooms/status": 1,
        "/api/agent-rooms": 1,
        "/api/agent-rooms/{agent_key}": 2,
        "/api/agent-rooms/{agent_key}/messages": 1,
        "/api/agent-rooms/{agent_key}/tasks": 1,
        "/api/agent-rooms/{agent_key}/notes": 1,
        "/api/agent-rooms/{agent_key}/notes/{note_key}": 1,
        "/api/company/charter": 1,
        "/api/company/status": 1,
        "/api/company/reconcile": 1,
        "/api/company/agents": 1,
        "/api/portfolio/status": 1,
        "/api/portfolio/repos": 1,
        "/api/portfolio/repos/{repo_name}": 1,
        "/api/portfolio/sync": 1,
        "/api/portfolio/repos/{repo_name}/missions": 1,
        "/api/system/schema": 1,
        "/health/ready": 1,
        "/metrics": 1,
        "/api/health": 1,
    }
    for path, count in required_paths.items():
        assert paths.count(path) == count, (path, paths.count(path))

    assert permission_for_request(
        "POST", "/api/commercial/license/import"
    ) == "commercial:license:manage"
    assert permission_for_request(
        "POST", "/api/commercial/releases/publish"
    ) == "commercial:release:publish"
    assert permission_for_request("POST", "/api/pilot/programs") == "pilot:manage"
    assert permission_for_request(
        "POST", "/api/pilot/programs/PILOT-1/gates"
    ) == "pilot:evidence"
    assert permission_for_request(
        "POST", "/api/pilot/programs/PILOT-1/decision"
    ) == "pilot:accept"
    assert permission_for_request("PATCH", "/api/agent-rooms/mira") == "agent-room:write"
    assert permission_for_request(
        "POST", "/api/agent-rooms/mira/messages"
    ) == "agent-room:message"
    assert permission_for_request(
        "POST", "/api/agent-rooms/mira/tasks"
    ) == "agent-room:assign"
    assert permission_for_request("POST", "/api/company/reconcile") == "api:write"
    assert permission_for_request("POST", "/api/portfolio/sync") == "registry:write"
    assert permission_for_request(
        "POST", "/api/portfolio/repos/CherryFlow/missions"
    ) == "mission:create"
    assert {
        "commercial:license:manage",
        "commercial:release:publish",
        "pilot:manage",
        "pilot:evidence",
        "pilot:accept",
        "agent-room:write",
        "agent-room:message",
        "agent-room:assign",
    }.issubset(EXECUTION_ACTIONS)


if __name__ == "__main__":
    run()
    print("BeezaOffice 0.16.1 Agent Rooms, Company and paddman Portfolio smoke test passed")
