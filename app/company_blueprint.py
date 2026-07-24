from __future__ import annotations

from typing import Any

COMPANY_KEY = "company:beeza-ai"
TENANT_KEY = "tenant:beeza"
BLUEPRINT_VERSION = "1.0.0"
REASONING_MODEL = "deepseek/deepseek-v4-pro"
FAST_MODEL = "deepseek/deepseek-v4-flash"
PRIMARY_RUNTIME = "openclaw"

COMPANY_CHARTER: dict[str, Any] = {
    "company_key": COMPANY_KEY,
    "tenant_key": TENANT_KEY,
    "name": "Beeza AI Company",
    "operating_system": "BeezaOffice",
    "purpose": "Build and operate useful AI products with governed agents, measurable outcomes and human accountability.",
    "operating_model": "AI-first, human-governed, ops-first and daily-use-first",
    "principles": [
        "One accountable owner for every action",
        "Evidence before confidence",
        "Start with a seven-day operational loop",
        "Escalate money, equity, legal, personal-data, security and production risk",
        "Do not count unverified output as business value",
        "Prefer reusable platform capability over one-off automation",
    ],
    "human_authority": {
        "final_approver": "human:owner",
        "approval_required_for": [
            "equity and shareholder resolutions",
            "money transfer and material spend",
            "contract signature and regulatory filing",
            "personal-data access or export",
            "destructive action and production change",
            "public claims of legal or security compliance",
        ],
    },
    "initial_business_goal": {
        "horizon_days": 30,
        "outcome": "Deploy BeezaOffice with OpenClaw, operate the executive cadence and secure the first design-partner pilot.",
        "north_star_metrics": [
            "one accepted customer pilot",
            "weekly active governed agents",
            "verified outcomes delivered",
            "SLA compliance",
            "value created versus governed cost",
        ],
    },
}

# key -> name, parent department, risk tier
DEPARTMENTS: dict[str, dict[str, str | None]] = {
    "dept:board": {"name": "Shareholders & Board", "parent": None, "risk": "HIGH"},
    "dept:executive": {"name": "Executive Office", "parent": "dept:board", "risk": "HIGH"},
    "dept:operations": {"name": "Operations", "parent": "dept:executive", "risk": "CRITICAL"},
    "dept:quality": {"name": "Quality & Evidence", "parent": "dept:operations", "risk": "HIGH"},
    "dept:platform": {"name": "Technology Platform", "parent": "dept:executive", "risk": "CRITICAL"},
    "dept:engineering": {"name": "Engineering", "parent": "dept:platform", "risk": "HIGH"},
    "dept:infrastructure": {"name": "Infrastructure & SRE", "parent": "dept:platform", "risk": "CRITICAL"},
    "dept:ai-data": {"name": "AI & Data", "parent": "dept:platform", "risk": "HIGH"},
    "dept:data": {"name": "Data & Analytics", "parent": "dept:ai-data", "risk": "HIGH"},
    "dept:product": {"name": "Product", "parent": "dept:executive", "risk": "NORMAL"},
    "dept:growth": {"name": "Growth & Revenue", "parent": "dept:executive", "risk": "NORMAL"},
    "dept:marketing": {"name": "Marketing", "parent": "dept:growth", "risk": "NORMAL"},
    "dept:sales": {"name": "Sales", "parent": "dept:growth", "risk": "NORMAL"},
    "dept:support": {"name": "Customer Success & Support", "parent": "dept:growth", "risk": "NORMAL"},
    "dept:finance": {"name": "Finance & Accounting", "parent": "dept:executive", "risk": "HIGH"},
    "dept:procurement": {"name": "Procurement & Vendors", "parent": "dept:finance", "risk": "HIGH"},
    "dept:people": {"name": "People Operations", "parent": "dept:executive", "risk": "HIGH"},
    "dept:security": {"name": "Security", "parent": "dept:executive", "risk": "CRITICAL"},
    "dept:legal": {"name": "Legal & Compliance", "parent": "dept:executive", "risk": "HIGH"},
}


def _agent(
    key: str,
    name: str,
    role: str,
    department: str,
    manager: str | None,
    level: str,
    skills: list[str],
    *,
    model: str | None = None,
    clearance: str = "CONFIDENTIAL",
    concurrency: int = 3,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "identity_key": f"agent:{key}",
        "name": name,
        "role": role,
        "department": department,
        "manager": manager,
        "level": level,
        "runtime": PRIMARY_RUNTIME,
        "model": model or (FAST_MODEL if level == "department" else REASONING_MODEL),
        "clearance": clearance,
        "concurrency": concurrency,
        "skills": skills,
        "capabilities": [
            f"level:{level}",
            f"department:{department.removeprefix('dept:')}",
            *skills,
        ],
        "tools": tools or ["beezaoffice", "openclaw", "document", "report"],
    }


AGENTS: list[dict[str, Any]] = [
    _agent(
        "shareholder-rep",
        "Shareholder Representative",
        "Shareholder and Board Representative",
        "dept:board",
        None,
        "board",
        ["enterprise-value", "capital-allocation", "dilution", "governance", "board-accountability"],
        clearance="RESTRICTED",
        concurrency=1,
        tools=["executive-dashboard", "board-pack", "approval-review", "decision-log"],
    ),
    _agent(
        "ceo",
        "Beeza CEO",
        "Chief Executive Officer",
        "dept:executive",
        "shareholder-rep",
        "executive",
        ["strategy", "portfolio", "capital-allocation", "company-priorities", "final-recommendation"],
        clearance="RESTRICTED",
        concurrency=3,
        tools=["executive-dashboard", "mission", "meeting", "approval-review", "decision-log"],
    ),
    _agent(
        "cherry",
        "Cherry",
        "Executive Secretary and Chief of Staff",
        "dept:executive",
        "ceo",
        "executive_staff",
        ["intake", "routing", "briefing", "agenda", "follow-up", "decision-log"],
        model=FAST_MODEL,
        clearance="CONFIDENTIAL",
        concurrency=8,
        tools=["messaging", "calendar", "meeting", "mission", "sessions-spawn", "cherry-org"],
    ),
    _agent("cfo", "Beeza CFO", "Chief Financial Officer", "dept:finance", "ceo", "executive", ["cashflow", "budget", "unit-economics", "pricing-guardrail", "tax-readiness"], clearance="RESTRICTED"),
    _agent("coo", "Beeza COO", "Chief Operating Officer", "dept:operations", "ceo", "executive", ["operations", "sla", "capacity", "delivery", "business-continuity"], clearance="RESTRICTED"),
    _agent("cto", "Beeza CTO", "Chief Technology Officer", "dept:platform", "ceo", "executive", ["architecture", "engineering", "ai-platform", "infrastructure", "technical-risk"], clearance="RESTRICTED"),
    _agent("cpo", "Beeza CPO", "Chief Product Officer", "dept:product", "ceo", "executive", ["product-strategy", "discovery", "roadmap", "activation", "retention"]),
    _agent("cmo", "Beeza CMO", "Chief Marketing Officer", "dept:marketing", "ceo", "executive", ["positioning", "brand", "acquisition", "content", "launch"]),
    _agent("cro", "Beeza CRO", "Chief Revenue Officer", "dept:sales", "ceo", "executive", ["revenue-model", "pricing", "sales-pipeline", "partnerships", "expansion"]),
    _agent("chro", "Beeza CHRO", "Chief Human Resources Officer", "dept:people", "ceo", "executive", ["org-design", "hiring", "capability", "performance", "culture"], clearance="RESTRICTED"),
    _agent("ciso", "Beeza CISO", "Chief Information Security Officer", "dept:security", "ceo", "executive", ["security", "privacy-controls", "incident-response", "access-control", "risk-register"], clearance="RESTRICTED", tools=["security-evidence", "incident", "approval-review", "audit", "kill-switch"]),
    _agent("clo", "Beeza CLO", "Chief Legal Officer", "dept:legal", "ceo", "executive", ["legal", "contracts", "privacy", "intellectual-property", "regulatory"], clearance="RESTRICTED"),
    _agent(
        "rabbit-boss",
        "Rabbit Boss",
        "Cross-functional Execution Commander",
        "dept:operations",
        "coo",
        "executive_staff",
        ["work-breakdown", "delegation", "delivery-control", "verification", "escalation", "rollback"],
        clearance="RESTRICTED",
        concurrency=10,
        tools=["coding", "mission", "task", "sessions-spawn", "runtime-dispatch", "cherry-org", "evidence"],
    ),
    _agent("head-finance", "Head of Finance", "Head of Finance and Accounting", "dept:finance", "cfo", "department", ["bookkeeping", "cash-position", "budget-control", "management-accounts", "tax-documents"], clearance="RESTRICTED"),
    _agent("head-operations", "Head of Operations", "Head of Operations", "dept:operations", "coo", "department", ["daily-operations", "sla-board", "workload", "quality-control", "runbooks"]),
    _agent("head-engineering", "Head of Engineering", "Head of Engineering", "dept:engineering", "cto", "department", ["software-delivery", "code-quality", "ci-cd", "release", "engineering-capacity"], tools=["github", "coding", "test-runner", "release", "rollback"]),
    _agent("head-infrastructure", "Head of Infrastructure", "Head of Infrastructure and Platform", "dept:infrastructure", "cto", "department", ["compute", "storage", "network", "virtualization", "platform-sre", "capacity"], clearance="RESTRICTED", tools=["monitoring", "runbook", "proxmox", "storage", "network", "change-plan"]),
    _agent("head-ai-data", "Head of AI and Data", "Head of AI and Data", "dept:ai-data", "cto", "department", ["llm-platform", "data-pipeline", "rag", "evaluation", "model-ops"], clearance="RESTRICTED", tools=["deepseek-v4", "openai-compatible-api", "evaluation", "data-pipeline", "model-ops"]),
    _agent("head-product", "Head of Product", "Head of Product", "dept:product", "cpo", "department", ["discovery", "backlog", "prd", "analytics", "experiments"]),
    _agent("head-marketing", "Head of Marketing", "Head of Marketing", "dept:marketing", "cmo", "department", ["campaigns", "content-calendar", "channel-ops", "funnel-metrics", "brand-assets"]),
    _agent("head-sales", "Head of Sales", "Head of Sales", "dept:sales", "cro", "department", ["pipeline", "qualification", "proposal", "closing", "forecast"]),
    _agent("head-customer-success", "Head of Customer Success", "Head of Customer Success and Support", "dept:support", "coo", "department", ["onboarding", "support-queue", "adoption", "retention", "voice-of-customer"]),
    _agent("head-people", "Head of People", "Head of People Operations", "dept:people", "chro", "department", ["recruiting-ops", "onboarding", "performance-cycle", "people-records", "policy-ops"], clearance="RESTRICTED"),
    _agent("head-security", "Head of Security Operations", "Head of Security Operations", "dept:security", "ciso", "department", ["soc-queue", "vulnerability-ops", "incident-triage", "access-review", "security-evidence"], clearance="RESTRICTED", tools=["security-evidence", "incident-triage", "access-review", "audit"]),
    _agent("head-legal", "Head of Legal Operations", "Head of Legal Operations", "dept:legal", "clo", "department", ["contract-ops", "legal-intake", "obligation-register", "compliance-evidence", "document-control"], clearance="RESTRICTED"),
    _agent("head-procurement", "Head of Procurement", "Head of Procurement and Vendor Management", "dept:procurement", "cfo", "department", ["procurement-queue", "vendor-due-diligence", "quote-comparison", "purchase-control", "vendor-sla"], clearance="RESTRICTED"),
]

MISSIONS: list[dict[str, Any]] = [
    {
        "key": "COMPANY-LAUNCH-001",
        "title": "Launch Beeza AI Company operating cadence",
        "commander": "Rabbit Boss",
        "status": "EXECUTING",
        "priority": "HIGH",
        "progress": 10,
        "waiting_for": "Human confirmation of the first commercial offer",
        "objective": "Activate the organization graph, establish daily and weekly operating rhythms, verify escalation gates and produce the first executive scorecard within seven days.",
    },
    {
        "key": "PILOT-FIRST-CUSTOMER-001",
        "title": "Secure and deliver the first BeezaOffice design-partner pilot",
        "commander": "Beeza CRO",
        "status": "QUEUED",
        "priority": "HIGH",
        "progress": 0,
        "waiting_for": "Target customer and approved pilot offer",
        "objective": "Select one painful workflow, define acceptance gates, deploy a governed OpenClaw pilot and obtain named human acceptance within thirty days.",
    },
    {
        "key": "EXEC-DAILY-BRIEF-001",
        "title": "Run the Beeza executive daily brief",
        "commander": "Cherry",
        "status": "QUEUED",
        "priority": "NORMAL",
        "progress": 0,
        "waiting_for": "Company launch mission evidence",
        "objective": "Publish a concise daily brief covering revenue, product, delivery, incidents, approvals, blocked work and the next accountable action.",
    },
]


def validate_blueprint() -> dict[str, int]:
    agent_keys = [agent["key"] for agent in AGENTS]
    if len(agent_keys) != len(set(agent_keys)):
        raise ValueError("Company blueprint contains duplicate agent keys")

    known_agents = set(agent_keys)
    known_departments = set(DEPARTMENTS)
    for agent in AGENTS:
        if agent["department"] not in known_departments:
            raise ValueError(f"Unknown department for {agent['key']}: {agent['department']}")
        manager = agent.get("manager")
        if manager and manager not in known_agents:
            raise ValueError(f"Unknown manager for {agent['key']}: {manager}")
        if manager == agent["key"]:
            raise ValueError(f"Agent cannot manage itself: {agent['key']}")

    for department_key, department in DEPARTMENTS.items():
        parent = department.get("parent")
        if parent and parent not in known_departments:
            raise ValueError(f"Unknown parent for {department_key}: {parent}")

    for agent in AGENTS:
        visited: set[str] = set()
        cursor: str | None = agent["key"]
        while cursor:
            if cursor in visited:
                raise ValueError(f"Management cycle detected at {cursor}")
            visited.add(cursor)
            row = next(item for item in AGENTS if item["key"] == cursor)
            cursor = row.get("manager")

    return {
        "departments": len(DEPARTMENTS),
        "agents": len(AGENTS),
        "missions": len(MISSIONS),
    }


BLUEPRINT_COUNTS = validate_blueprint()
