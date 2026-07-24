from __future__ import annotations

from typing import Any

PORTFOLIO_OWNER = "paddman"
PORTFOLIO_VERSION = "1.0.0"


def _repo(
    name: str,
    visibility: str,
    default_branch: str,
    category: str,
    department: str,
    accountable_agent: str,
    sponsor_agent: str,
    purpose: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "full_name": f"{PORTFOLIO_OWNER}/{name}",
        "visibility": visibility,
        "default_branch": default_branch,
        "category": category,
        "department": department,
        "accountable_agent": accountable_agent,
        "sponsor_agent": sponsor_agent,
        "purpose": purpose,
        "lifecycle": "ACTIVE",
        "classification_source": "beeza-company-bootstrap",
    }


REPOSITORIES: list[dict[str, Any]] = [
    _repo("Beezaoffice", "public", "main", "company-control", "dept:executive", "cherry", "ceo", "AI workforce operating system and company control plane."),
    _repo("C-level", "private", "main", "company-control", "dept:executive", "cherry", "ceo", "Shareholder, C-Level and department-head decision service."),
    _repo("openclawxcherry", "public", "main", "company-control", "dept:platform", "head-ai-data", "cto", "OpenClaw runtime and Cherry organization integration."),
    _repo("RABBITAGENT", "public", "main", "company-control", "dept:operations", "rabbit-boss", "coo", "Rabbit Boss execution-agent workspace."),
    _repo("cherryagent", "public", "main", "company-control", "dept:engineering", "head-engineering", "cto", "Cherry agent orchestration runtime."),
    _repo("cherryteam", "public", "main", "company-control", "dept:operations", "head-operations", "coo", "Multi-agent team coordination workspace."),
    _repo("agent-town-cherry", "public", "main", "company-control", "dept:product", "head-product", "cpo", "Agent workspace and product experience."),
    _repo("AIaaS", "private", "main", "ai-platform", "dept:ai-data", "head-ai-data", "cto", "AI-as-a-Service platform workspace."),
    _repo("atlas-control-plane", "public", "main", "ai-platform", "dept:infrastructure", "head-infrastructure", "cto", "AI infrastructure and control-plane service."),
    _repo("CherryFlow", "public", "main", "ai-platform", "dept:engineering", "head-engineering", "cto", "Local AI workflow platform."),
    _repo("mfmas", "public", "main", "ai-platform", "dept:ai-data", "head-ai-data", "cto", "Memory capability for multi-agent systems."),
    _repo("mfmas-memory-for-multi-agent-systems", "public", "main", "ai-platform", "dept:ai-data", "head-ai-data", "cto", "Multi-agent memory research and implementation."),
    _repo("cline", "public", "main", "developer-tools", "dept:engineering", "head-engineering", "cto", "Developer-agent tooling and reference implementation."),
    _repo("dev-box-test", "private", "main", "developer-tools", "dept:engineering", "head-engineering", "cto", "Private development environment test workspace."),
    _repo("-cherry-finance", "public", "main", "product", "dept:finance", "head-finance", "cfo", "Cherry finance product workspace."),
    _repo("cherrydeskx", "public", "main", "product", "dept:product", "head-product", "cpo", "CherryDeskX product workspace."),
    _repo("CherryInsight", "public", "main", "product", "dept:ai-data", "head-ai-data", "cpo", "Insight and analytics product workspace."),
    _repo("cherryvoice", "public", "main", "product", "dept:product", "head-product", "cpo", "Cherry voice product workspace."),
    _repo("OmniVoicexcherry", "public", "master", "product", "dept:product", "head-product", "cpo", "OmniVoice and Cherry voice integration."),
    _repo("MeuxCompanion", "public", "main", "product-research", "dept:product", "head-product", "cpo", "Companion-product research and reference workspace."),
    _repo("beezashopplan", "private", "main", "commercial", "dept:sales", "head-sales", "cro", "Beeza shop and commercial planning workspace."),
    _repo("alertsystem", "public", "master", "operations", "dept:infrastructure", "head-infrastructure", "cto", "Infrastructure alerting system."),
    _repo("paddman", "public", "main", "portfolio-meta", "dept:executive", "cherry", "ceo", "Owner profile and portfolio metadata repository."),
]


def repository_map() -> dict[str, dict[str, Any]]:
    return {str(item["name"]): dict(item) for item in REPOSITORIES}


def validate_portfolio() -> dict[str, int]:
    names = [str(item["name"]) for item in REPOSITORIES]
    full_names = [str(item["full_name"]) for item in REPOSITORIES]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate repository name in paddman portfolio")
    if len(full_names) != len(set(full_names)):
        raise ValueError("Duplicate repository full_name in paddman portfolio")
    for item in REPOSITORIES:
        if not item["accountable_agent"] or not item["sponsor_agent"]:
            raise ValueError(f"Repository {item['name']} is missing ownership")
        if not str(item["department"]).startswith("dept:"):
            raise ValueError(f"Repository {item['name']} has an invalid department")
    return {
        "repositories": len(REPOSITORIES),
        "categories": len({str(item["category"]) for item in REPOSITORIES}),
        "departments": len({str(item["department"]) for item in REPOSITORIES}),
    }


PORTFOLIO_COUNTS = validate_portfolio()
