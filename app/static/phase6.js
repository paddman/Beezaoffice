(() => {
  const phase6 = {
    context: null,
    identities: [],
    roles: [],
    policies: [],
    approvals: [],
    audit: [],
    integrity: null,
    initialized: false,
    timer: null,
  };

  const originalOperatorApi = operatorApi;
  operatorApi = async function governedOperatorApi(path, options = {}, promptForToken = true) {
    const identity = localStorage.getItem("beezaIdentity") || "human:owner";
    const risk = localStorage.getItem("beezaRiskLevel") || "NORMAL";
    const classification = localStorage.getItem("beezaDataClassification") || "INTERNAL";
    const estimatedCost = localStorage.getItem("beezaEstimatedCost") || "0";
    const approvalKey = localStorage.getItem("beezaApprovalKey") || "";
    return originalOperatorApi(path, {
      ...options,
      headers: {
        ...(options.headers || {}),
        "X-Beeza-Identity": identity,
        "X-Beeza-Risk-Level": risk,
        "X-Beeza-Data-Classification": classification,
        "X-Beeza-Estimated-Cost-USD": estimatedCost,
        ...(approvalKey ? { "X-Beeza-Approval-Key": approvalKey } : {}),
      },
    }, promptForToken);
  };

  function currentIdentity() {
    return localStorage.getItem("beezaIdentity") || "human:owner";
  }

  function canReadGovernance(identity) {
    return (identity.permissions || []).some((permission) => (
      permission === "*" || permission === "governance:read" || permission === "governance:*"
    ));
  }

  function installUi() {
    if (document.querySelector("#governanceCenter")) return;

    const nav = [...document.querySelectorAll(".nav-item")]
      .find((button) => button.textContent.trim().startsWith("Governance"));
    if (nav) {
      nav.id = "governanceNav";
      nav.innerHTML = 'Governance <span id="governanceNavCount">0</span>';
    }

    const panel = document.createElement("section");
    panel.className = "panel governance-panel";
    panel.id = "governanceCenter";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 6 · GOVERNANCE & IDENTITY</p><h2>AI Workforce Control Plane</h2></div>
        <div class="governance-header-state"><span id="governanceState">Starting</span><b id="governancePendingCount">0</b></div>
      </div>
      <p class="dispatch-intro">Every human, agent, service and runtime operates under an identity, role, clearance, policy, budget and hash-chained audit record. High-risk work can require a second approver before execution.</p>
      <div class="governance-toolbar">
        <label>Operating identity<select id="governanceIdentity"></select></label>
        <label>Risk level<select id="governanceRisk"><option>LOW</option><option selected>NORMAL</option><option>HIGH</option><option>CRITICAL</option></select></label>
        <label>Data classification<select id="governanceClassification"><option>PUBLIC</option><option selected>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
        <label>Estimated cost USD<input id="governanceCost" type="number" min="0" step="0.01" value="0" /></label>
      </div>
      <div id="governanceSummary" class="governance-summary"></div>
      <div class="governance-killbar">
        <div><strong>Runtime execution kill switch</strong><small id="governanceKillReason">Loading control state…</small></div>
        <div><button class="primary" id="governanceEnableExecution">Enable execution</button><button class="danger-button" id="governanceDisableExecution">Disable execution</button><button class="secondary" id="governanceClearApproval">Clear approval key</button></div>
      </div>
      <div class="governance-grid">
        <div class="governance-column">
          <section class="governance-box">
            <div class="governance-box-head"><div><strong>Identity registry</strong><small>Humans, agents, services and runtime principals</small></div><div><span id="identityCount" class="governance-tag">0</span></div></div>
            <div id="governanceIdentities" class="governance-list"></div>
          </section>
          <section class="governance-box">
            <div class="governance-box-head"><div><strong>Policy matrix</strong><small>RBAC is evaluated first, then risk, clearance, budget and policy</small></div><div><span id="policyCount" class="governance-tag">0</span></div></div>
            <div id="governancePolicies" class="governance-list"></div>
          </section>
        </div>
        <div class="governance-column">
          <section class="governance-box">
            <div class="governance-box-head"><div><strong>Approval queue</strong><small>Requester and approver identities must be separate</small></div><div><span id="approvalCount" class="governance-tag pending">0</span></div></div>
            <div id="governanceApprovals" class="governance-list"></div>
          </section>
          <section class="governance-box">
            <div class="governance-box-head"><div><strong>Immutable audit ledger</strong><small>SHA-256 chained operational evidence</small></div><div><button class="secondary" id="verifyAudit">Verify chain</button></div></div>
            <div id="auditChainState" class="governance-list"></div>
            <div id="governanceAudit" class="governance-list"></div>
          </section>
        </div>
      </div>
      <p id="governanceMessage" class="governance-message"></p>
    `;
    document.querySelector("#meetingManager")?.after(panel);

    nav?.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#governanceIdentity").addEventListener("change", async (event) => {
      localStorage.setItem("beezaIdentity", event.target.value);
      localStorage.removeItem("beezaApprovalKey");
      await loadGovernance();
    });
    panel.querySelector("#governanceRisk").addEventListener("change", (event) => localStorage.setItem("beezaRiskLevel", event.target.value));
    panel.querySelector("#governanceClassification").addEventListener("change", (event) => localStorage.setItem("beezaDataClassification", event.target.value));
    panel.querySelector("#governanceCost").addEventListener("change", (event) => localStorage.setItem("beezaEstimatedCost", event.target.value || "0"));
    panel.querySelector("#governanceEnableExecution").addEventListener("click", () => setExecution(true));
    panel.querySelector("#governanceDisableExecution").addEventListener("click", () => setExecution(false));
    panel.querySelector("#governanceClearApproval").addEventListener("click", () => {
      localStorage.removeItem("beezaApprovalKey");
      showMessage("Approval key cleared.", "success");
      renderGovernanceSummary();
    });
    panel.querySelector("#verifyAudit").addEventListener("click", verifyAuditChain);

    document.querySelector("#governanceRisk").value = localStorage.getItem("beezaRiskLevel") || "NORMAL";
    document.querySelector("#governanceClassification").value = localStorage.getItem("beezaDataClassification") || "INTERNAL";
    document.querySelector("#governanceCost").value = localStorage.getItem("beezaEstimatedCost") || "0";
  }

  function showMessage(message, type = "") {
    const node = document.querySelector("#governanceMessage");
    if (!node) return;
    node.textContent = message;
    node.className = `governance-message ${type}`;
  }

  function renderGovernanceSummary() {
    const container = document.querySelector("#governanceSummary");
    if (!container || !phase6.context) return;
    const context = phase6.context;
    const identity = context.identity || {};
    const budget = context.budget || {};
    const execution = context.execution || {};
    const activeApproval = localStorage.getItem("beezaApprovalKey") || "none";
    const cards = [
      ["Enforcement", context.enforced ? "ENFORCED" : "DISABLED", "RBAC + policy middleware"],
      ["Execution", execution.enabled ? "ENABLED" : "STOPPED", execution.reason || "No reason recorded", execution.enabled ? "execution-enabled" : "execution-disabled"],
      ["Identity", identity.name || identity.key || "—", identity.type || "—"],
      ["Clearance", identity.clearance || "—", identity.department_key || "No department"],
      ["Daily budget", `$${Number(budget.daily || 0).toFixed(2)} / $${Number(budget.daily_limit || 0).toFixed(2)}`, `Monthly $${Number(budget.monthly || 0).toFixed(2)}`],
      ["Approval key", activeApproval, activeApproval === "none" ? "No approved request armed" : "Applied to governed mutations"],
    ];
    container.innerHTML = cards.map(([label, value, detail, extra = ""]) => `
      <article class="governance-stat ${extra}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>
    `).join("");
    document.querySelector("#governanceKillReason").textContent = `${execution.enabled ? "Execution enabled" : "Execution disabled"} · ${execution.reason || "no reason"} · ${execution.changed_by || "system"}`;
  }

  function renderIdentitySelector() {
    const select = document.querySelector("#governanceIdentity");
    if (!select) return;
    const available = phase6.identities.filter(canReadGovernance);
    select.innerHTML = available.map((identity) => `
      <option value="${escapeHtml(identity.key)}">${escapeHtml(identity.name)} · ${escapeHtml(identity.type)} · ${escapeHtml(identity.clearance)}</option>
    `).join("");
    if (available.some((identity) => identity.key === currentIdentity())) select.value = currentIdentity();
  }

  function renderIdentities() {
    const container = document.querySelector("#governanceIdentities");
    document.querySelector("#identityCount").textContent = String(phase6.identities.length);
    if (!container) return;
    if (!phase6.identities.length) {
      container.innerHTML = '<p class="governance-empty">No governance identities registered.</p>';
      return;
    }
    container.innerHTML = phase6.identities.map((identity) => {
      const permissions = (identity.permissions || []).slice(0, 10);
      return `
        <article class="identity-row">
          <header><div><strong>${escapeHtml(identity.name)}</strong><small>${escapeHtml(identity.key)} · ${escapeHtml(identity.department_key || "unassigned")}</small></div><span class="governance-tag ${safeClass(identity.status)}">${escapeHtml(identity.type)} · ${escapeHtml(identity.status)}</span></header>
          <p>Clearance ${escapeHtml(identity.clearance)} · Daily $${Number(identity.daily_budget_usd).toFixed(2)} · Monthly $${Number(identity.monthly_budget_usd).toFixed(2)}</p>
          <div class="identity-permissions">${permissions.map((permission) => `<span>${escapeHtml(permission)}</span>`).join("")}${(identity.permissions || []).length > permissions.length ? `<span>+${identity.permissions.length - permissions.length}</span>` : ""}</div>
        </article>
      `;
    }).join("");
  }

  function renderPolicies() {
    const container = document.querySelector("#governancePolicies");
    document.querySelector("#policyCount").textContent = String(phase6.policies.length);
    if (!container) return;
    if (!phase6.policies.length) {
      container.innerHTML = '<p class="governance-empty">No policy rules configured.</p>';
      return;
    }
    container.innerHTML = phase6.policies.map((policy) => `
      <article class="policy-row">
        <header><div><strong>${escapeHtml(policy.name)}</strong><small>${escapeHtml(policy.key)} · priority ${policy.priority}</small></div><span class="governance-tag ${safeClass(policy.effect)}">${escapeHtml(policy.effect)}</span></header>
        <p>Action ${escapeHtml(policy.action_pattern)} · Risk ${escapeHtml(policy.risk_levels?.join(", ") || "all")} · Clearance ${escapeHtml(policy.minimum_clearance)}${policy.maximum_cost_usd !== null ? ` · Cost over $${Number(policy.maximum_cost_usd).toFixed(2)}` : ""}</p>
      </article>
    `).join("");
  }

  function approvalButtons(approval) {
    const identity = currentIdentity();
    if (approval.status === "PENDING" && approval.requester_identity !== identity) {
      return `<button class="primary" data-approval-decision="APPROVED" data-approval-key="${escapeHtml(approval.key)}">Approve</button><button class="danger-button" data-approval-decision="DENIED" data-approval-key="${escapeHtml(approval.key)}">Deny</button>`;
    }
    if (approval.status === "APPROVED" && approval.requester_identity === identity) {
      return `<button class="primary" data-use-approval="${escapeHtml(approval.key)}">Use approval</button>`;
    }
    return "";
  }

  function renderApprovals() {
    const container = document.querySelector("#governanceApprovals");
    const pending = phase6.approvals.filter((approval) => approval.status === "PENDING").length;
    document.querySelector("#approvalCount").textContent = String(pending);
    document.querySelector("#governancePendingCount").textContent = String(pending);
    document.querySelector("#governanceNavCount").textContent = String(pending + (phase6.context?.execution?.enabled ? 0 : 1));
    if (!container) return;
    if (!phase6.approvals.length) {
      container.innerHTML = '<p class="governance-empty">No approval requests.</p>';
      return;
    }
    container.innerHTML = phase6.approvals.slice(0, 100).map((approval) => `
      <article class="approval-row">
        <header><div><strong>${escapeHtml(approval.action)}</strong><small>${escapeHtml(approval.key)} · ${escapeHtml(approval.requester_identity)}</small></div><span class="governance-tag ${safeClass(approval.status)}">${escapeHtml(approval.status)}</span></header>
        <p>${escapeHtml(approval.reason)}<br />Target ${escapeHtml(approval.target || "—")} · Risk ${escapeHtml(approval.risk_level)} · Expires ${escapeHtml(formatDateTime(approval.expires_at))}</p>
        <div class="approval-actions">${approvalButtons(approval)}</div>
      </article>
    `).join("");
    container.querySelectorAll("[data-approval-decision]").forEach((button) => {
      button.addEventListener("click", () => decideApproval(button.dataset.approvalKey, button.dataset.approvalDecision));
    });
    container.querySelectorAll("[data-use-approval]").forEach((button) => {
      button.addEventListener("click", () => {
        localStorage.setItem("beezaApprovalKey", button.dataset.useApproval);
        showMessage(`Approval ${button.dataset.useApproval} armed for the next matching action.`, "success");
        renderGovernanceSummary();
      });
    });
  }

  function renderAudit() {
    const integrity = phase6.integrity;
    const stateNode = document.querySelector("#auditChainState");
    if (stateNode) {
      if (!integrity) stateNode.innerHTML = '<p class="governance-empty">Audit chain not verified.</p>';
      else stateNode.innerHTML = `<div class="audit-chain-state ${integrity.valid ? "valid" : "invalid"}"><strong>${integrity.valid ? "VALID" : "BROKEN"}</strong><span>${integrity.checked} records · head ${escapeHtml(String(integrity.head_hash || "").slice(0, 16))}${integrity.broken_at ? ` · broken at ${escapeHtml(integrity.broken_at)}` : ""}</span></div>`;
    }
    const container = document.querySelector("#governanceAudit");
    if (!container) return;
    if (!phase6.audit.length) {
      container.innerHTML = '<p class="governance-empty">No governed mutations recorded yet.</p>';
      return;
    }
    container.innerHTML = phase6.audit.slice(0, 100).map((record) => `
      <article class="audit-row">
        <header><div><strong>${escapeHtml(record.action)}</strong><small>${escapeHtml(record.identity_key)} · ${escapeHtml(record.method)} ${escapeHtml(record.path)}</small></div><span class="governance-tag ${safeClass(record.outcome)}">${escapeHtml(record.outcome)} ${record.status_code}</span></header>
        <p>${escapeHtml(formatDateTime(record.created_at))} · Request ${escapeHtml(record.request_id)}</p>
        <code class="audit-hash">${escapeHtml(record.record_hash)}</code>
      </article>
    `).join("");
  }

  function renderGovernance() {
    renderIdentitySelector();
    renderGovernanceSummary();
    renderIdentities();
    renderPolicies();
    renderApprovals();
    renderAudit();
  }

  async function loadGovernance(silent = false) {
    if (!silent) document.querySelector("#governanceState").textContent = "Loading";
    try {
      const [context, identities, roles, policies, approvals, audit, integrity] = await Promise.all([
        operatorApi("/api/governance/context", {}, true),
        operatorApi("/api/governance/identities", {}, true),
        operatorApi("/api/governance/roles", {}, true),
        operatorApi("/api/governance/policies", {}, true),
        operatorApi("/api/governance/approvals?limit=100", {}, true),
        operatorApi("/api/governance/audit?limit=100", {}, true),
        operatorApi("/api/governance/audit/verify?limit=5000", {}, true),
      ]);
      phase6.context = context;
      phase6.identities = identities;
      phase6.roles = roles;
      phase6.policies = policies;
      phase6.approvals = approvals;
      phase6.audit = audit;
      phase6.integrity = integrity;
      renderGovernance();
      document.querySelector("#governanceState").textContent = "Enforced";
    } catch (error) {
      document.querySelector("#governanceState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function setExecution(enabled) {
    const verb = enabled ? "enable" : "disable";
    const reason = window.prompt(`Reason to ${verb} runtime execution`, enabled ? "Operations approved to resume" : "Emergency operator stop") || "";
    if (reason.length < 3) return;
    try {
      await operatorApi("/api/governance/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ execution_enabled: enabled, reason }),
      });
      showMessage(`Runtime execution ${enabled ? "enabled" : "disabled"}.`, "success");
      await loadGovernance(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function decideApproval(key, decision) {
    const note = window.prompt(`${decision === "APPROVED" ? "Approval" : "Denial"} note`, decision === "APPROVED" ? "Reviewed and approved under governance policy" : "Denied after risk review") || "";
    try {
      await operatorApi(`/api/governance/approvals/${encodeURIComponent(key)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note }),
      });
      showMessage(`${key} ${decision.toLowerCase()}.`, "success");
      await loadGovernance(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function verifyAuditChain() {
    try {
      phase6.integrity = await operatorApi("/api/governance/audit/verify?limit=50000", {}, true);
      renderAudit();
      showMessage(phase6.integrity.valid ? "Audit chain verified." : `Audit chain broken at ${phase6.integrity.broken_at}.`, phase6.integrity.valid ? "success" : "error");
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function startPolling() {
    if (phase6.timer) clearInterval(phase6.timer);
    phase6.timer = setInterval(() => {
      if (!document.hidden) void loadGovernance(true);
    }, 10000);
  }

  async function initialize() {
    if (phase6.initialized) return;
    phase6.initialized = true;
    installUi();
    startPolling();
    await loadGovernance();
  }

  void initialize();
})();
