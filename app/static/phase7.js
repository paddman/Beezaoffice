(() => {
  const phase7 = {
    agents: [],
    stats: null,
    organization: null,
    skills: [],
    delegations: [],
    selected: null,
    mode: "agents",
    initialized: false,
    timer: null,
  };

  function installUi() {
    if (document.querySelector("#agentRegistry")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "registryNav";
    nav.innerHTML = 'Agent Registry <span id="registryNavCount">0</span>';
    document.querySelector("#organizationNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel registry-panel";
    panel.id = "agentRegistry";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 7 · AGENT REGISTRY & ORGANIZATION GRAPH</p><h2>AI Workforce Directory</h2></div>
        <div class="registry-header-state"><span id="registryState">Starting</span><b id="registryCount">0</b></div>
      </div>
      <p class="dispatch-intro">Search the workforce by department, runtime, availability and skill. Profiles carry reporting lines, capabilities, tool boundaries, concurrency, reliability, delegation and live workload.</p>
      <div class="registry-toolbar">
        <label>Search<input id="registrySearch" placeholder="name, role, key or identity" /></label>
        <label>Department<select id="registryDepartment"><option value="">All departments</option></select></label>
        <label>Runtime<select id="registryRuntime"><option value="">All runtimes</option></select></label>
        <label>Availability<select id="registryAvailability"><option value="">All states</option><option>AVAILABLE</option><option>BUSY</option><option>WAITING</option><option>OFFLINE</option><option>MAINTENANCE</option></select></label>
        <label>Skill<select id="registrySkill"><option value="">All skills</option></select></label>
        <div class="registry-toolbar-actions"><button class="secondary" id="registryReconcile">Reconcile</button><button class="primary" id="registryNewAgent">+ Agent</button></div>
      </div>
      <div id="registryStats" class="registry-stats"></div>
      <div class="registry-layout">
        <section class="registry-box">
          <div class="registry-box-head"><div><strong>Workforce directory</strong><small>Registered identities and live capacity</small></div><div class="registry-tabs"><button class="registry-tab active" data-registry-mode="agents">Agents</button><button class="registry-tab" data-registry-mode="organization">Organization</button><button class="registry-tab" data-registry-mode="skills">Skills</button></div></div>
          <div id="registryDirectory" class="registry-agent-list"></div>
        </section>
        <section class="registry-box">
          <div class="registry-box-head"><div><strong id="registryDetailTitle">Agent profile</strong><small id="registryDetailSubtitle">Chain of command, workload and capabilities</small></div><div id="registryDetailActions" class="registry-actions"></div></div>
          <div id="registryDetail" class="registry-detail"><p class="registry-detail-empty">Select an agent to inspect the full profile.</p></div>
        </section>
      </div>
      <p id="registryMessage" class="registry-message"></p>
    `;
    document.querySelector("#governanceCenter")?.after(panel);

    const agentDialog = document.createElement("dialog");
    agentDialog.id = "registryAgentDialog";
    agentDialog.innerHTML = `
      <form method="dialog" id="registryAgentForm">
        <div class="dialog-head"><div><p class="eyebrow">WORKFORCE REGISTRATION</p><h2>Register Agent</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="registry-form-grid">
          <label>Agent key<input id="newAgentKey" required minlength="2" pattern="[a-z0-9][a-z0-9._-]*" placeholder="network-analyst" /></label>
          <label>Identity key<input id="newAgentIdentity" required minlength="3" placeholder="agent:network-analyst" /></label>
          <label>Display name<input id="newAgentName" required minlength="2" placeholder="Nami" /></label>
          <label>Role title<input id="newAgentRole" required minlength="2" placeholder="Network Analyst" /></label>
          <label>Department<select id="newAgentDepartment" required></select></label>
          <label>Manager<select id="newAgentManager"><option value="">No manager</option></select></label>
          <label>Preferred runtime<select id="newAgentRuntime" required></select></label>
          <label>Maximum concurrency<input id="newAgentConcurrency" type="number" min="1" max="100" value="2" required /></label>
          <label>Data clearance<select id="newAgentClearance"><option>PUBLIC</option><option selected>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label>Version<input id="newAgentVersion" value="1.0.0" required /></label>
          <label class="full">Skills<textarea id="newAgentSkills" placeholder="networking\nbgp\nfirewall"></textarea></label>
          <label class="full">Capabilities<textarea id="newAgentCapabilities" placeholder="network-diagnostics\nchange-plan"></textarea></label>
          <label class="full">Allowed tools<textarea id="newAgentTools" placeholder="prometheus\nnetwork-cli\nrunbook"></textarea></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Register agent</button></div>
        <p id="registryAgentFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(agentDialog);

    const delegationDialog = document.createElement("dialog");
    delegationDialog.id = "registryDelegationDialog";
    delegationDialog.innerHTML = `
      <form method="dialog" id="registryDelegationForm">
        <div class="dialog-head"><div><p class="eyebrow">CHAIN OF COMMAND</p><h2>Create Delegation</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="registry-form-grid">
          <label>Source agent<select id="delegationSource" required></select></label>
          <label>Target agent<select id="delegationTarget" required></select></label>
          <label class="full">Delegated scope<textarea id="delegationScope" placeholder="mission:coordinate\napproval:recommend\nreport:signoff"></textarea></label>
          <label class="full">Reason<textarea id="delegationReason" required minlength="3" placeholder="Temporary delegation during incident response coverage."></textarea></label>
          <label>Ends at<input id="delegationEnds" type="datetime-local" /></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create delegation</button></div>
        <p id="registryDelegationMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(delegationDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelectorAll("[data-registry-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.registryMode)));
    panel.querySelector("#registrySearch").addEventListener("input", debounce(loadAgents, 250));
    ["#registryDepartment", "#registryRuntime", "#registryAvailability", "#registrySkill"].forEach((selector) => panel.querySelector(selector).addEventListener("change", loadAgents));
    panel.querySelector("#registryReconcile").addEventListener("click", reconcileRegistry);
    panel.querySelector("#registryNewAgent").addEventListener("click", openAgentDialog);
    agentDialog.querySelector("#registryAgentForm").addEventListener("submit", createAgent);
    delegationDialog.querySelector("#registryDelegationForm").addEventListener("submit", createDelegation);
  }

  function debounce(fn, wait) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  function lines(value) {
    return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function showMessage(message, type = "") {
    const node = document.querySelector("#registryMessage");
    if (!node) return;
    node.textContent = message;
    node.className = `registry-message ${type}`;
  }

  function setMode(mode) {
    phase7.mode = mode;
    document.querySelectorAll("[data-registry-mode]").forEach((button) => button.classList.toggle("active", button.dataset.registryMode === mode));
    renderDirectory();
    if (mode !== "agents") {
      phase7.selected = null;
      renderDetail();
    }
  }

  function renderStats() {
    const stats = phase7.stats || {};
    const cards = [
      ["Registered", stats.registered_agents || 0, `Target ${stats.scale_target || 1000}`],
      ["Active", stats.active_agents || 0, `${stats.departments || 0} departments`],
      ["Capacity", stats.available_capacity || 0, `${stats.current_workload || 0}/${stats.total_capacity || 0} occupied`],
      ["Utilization", `${Math.round(Number(stats.utilization || 0) * 100)}%`, "Concurrent work slots"],
      ["Reliability", `${Math.round(Number(stats.average_reliability || 0) * 100)}%`, "Average agent score"],
      ["Skills", stats.skills || 0, `${Object.keys(stats.runtime_distribution || {}).length} runtimes`],
    ];
    document.querySelector("#registryStats").innerHTML = cards.map(([label, value, detail]) => `<article class="registry-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
    document.querySelector("#registryCount").textContent = String(stats.registered_agents || 0);
    document.querySelector("#registryNavCount").textContent = String((stats.availability || {}).BUSY || 0);
  }

  function renderAgentDirectory() {
    const container = document.querySelector("#registryDirectory");
    if (!phase7.agents.length) {
      container.innerHTML = '<p class="registry-detail-empty">No agents match the current filters.</p>';
      return;
    }
    container.innerHTML = phase7.agents.map((agent) => `
      <button class="registry-agent-card ${phase7.selected?.key === agent.key ? "active" : ""}" data-registry-agent="${escapeHtml(agent.key)}">
        <header><div><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.key)} · ${escapeHtml(agent.role)}</small></div><span class="registry-status ${safeClass(agent.availability)}">${escapeHtml(agent.availability)}</span></header>
        <p>${escapeHtml(agent.department_key)} · ${escapeHtml(runtimeName(agent.preferred_runtime_key))}<br />${escapeHtml((agent.skills || []).slice(0, 4).join(" · ") || "No skills registered")}</p>
        <footer><span>Reliability ${Math.round(Number(agent.reliability_score) * 100)}%</span><span>${agent.current_workload}/${agent.max_concurrency} workload</span></footer>
      </button>
    `).join("");
    container.querySelectorAll("[data-registry-agent]").forEach((button) => button.addEventListener("click", () => selectAgent(button.dataset.registryAgent)));
  }

  function renderOrganizationDirectory() {
    const container = document.querySelector("#registryDirectory");
    const graph = phase7.organization || { nodes: [] };
    const departments = graph.nodes.filter((node) => node.type === "department");
    const agents = graph.nodes.filter((node) => node.type === "agent");
    container.className = "registry-org-view";
    container.innerHTML = departments.map((department) => {
      const members = agents.filter((agent) => agent.department_key === department.id);
      if (!members.length) return "";
      return `<section class="registry-department"><header><strong>${escapeHtml(department.label)}</strong><span>${members.length} agents · ${escapeHtml(department.risk_tier || "NORMAL")}</span></header><div class="registry-department-members">${members.map((agent) => `<button class="registry-org-agent" data-registry-agent="${escapeHtml(agent.id)}"><strong>${escapeHtml(agent.label)}</strong><small>${escapeHtml(agent.role)}<br />${escapeHtml(agent.manager_agent_key ? `Reports to ${agent.manager_agent_key}` : "Top-level")}</small></button>`).join("")}</div></section>`;
    }).join("") || '<p class="registry-detail-empty">Organization graph is empty.</p>';
    container.querySelectorAll("[data-registry-agent]").forEach((button) => button.addEventListener("click", async () => {
      phase7.mode = "agents";
      document.querySelectorAll("[data-registry-mode]").forEach((tab) => tab.classList.toggle("active", tab.dataset.registryMode === "agents"));
      await selectAgent(button.dataset.registryAgent);
    }));
  }

  function renderSkillDirectory() {
    const container = document.querySelector("#registryDirectory");
    container.className = "registry-agent-list";
    container.innerHTML = `<div class="registry-skill-list">${phase7.skills.map((skill) => `<button class="registry-skill" data-registry-skill="${escapeHtml(skill.skill)}"><strong>${escapeHtml(skill.skill)}</strong><small>${skill.agent_count} agents · ${skill.available_count} available · reliability ${Math.round(Number(skill.average_reliability) * 100)}%</small></button>`).join("")}</div>` || '<p class="registry-detail-empty">No skills registered.</p>';
    container.querySelectorAll("[data-registry-skill]").forEach((button) => button.addEventListener("click", async () => {
      document.querySelector("#registrySkill").value = button.dataset.registrySkill;
      phase7.mode = "agents";
      document.querySelectorAll("[data-registry-mode]").forEach((tab) => tab.classList.toggle("active", tab.dataset.registryMode === "agents"));
      await loadAgents();
    }));
  }

  function renderDirectory() {
    const container = document.querySelector("#registryDirectory");
    container.className = phase7.mode === "organization" ? "registry-org-view" : "registry-agent-list";
    if (phase7.mode === "organization") renderOrganizationDirectory();
    else if (phase7.mode === "skills") renderSkillDirectory();
    else renderAgentDirectory();
  }

  function renderDetailActions(agent) {
    const container = document.querySelector("#registryDetailActions");
    if (!agent || phase7.mode !== "agents") {
      container.innerHTML = "";
      return;
    }
    const nextStatus = agent.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE";
    container.innerHTML = `<button class="secondary" data-registry-action="heartbeat">Heartbeat</button><button class="secondary" data-registry-action="delegate">Delegate</button><button class="${nextStatus === "SUSPENDED" ? "danger-button" : "primary"}" data-registry-action="status">${nextStatus === "SUSPENDED" ? "Suspend" : "Activate"}</button>`;
    container.querySelectorAll("[data-registry-action]").forEach((button) => button.addEventListener("click", () => agentAction(button.dataset.registryAction)));
  }

  function renderDetail() {
    const container = document.querySelector("#registryDetail");
    const agent = phase7.selected;
    document.querySelector("#registryDetailTitle").textContent = phase7.mode === "organization" ? "Organization graph" : phase7.mode === "skills" ? "Skill matrix" : "Agent profile";
    document.querySelector("#registryDetailSubtitle").textContent = phase7.mode === "agents" ? "Chain of command, workload and capabilities" : "Select an item from the directory";
    renderDetailActions(agent);
    if (!agent || phase7.mode !== "agents") {
      container.innerHTML = '<p class="registry-detail-empty">Select an agent to inspect the full profile.</p>';
      return;
    }
    const utilization = Math.min(100, Math.round(Number(agent.utilization || 0) * 100));
    const directReports = (agent.direct_reports || []).map((item) => `<article class="registry-relation"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.key)} · ${escapeHtml(item.role)}</small></article>`).join("") || '<p class="registry-detail-empty">No direct reports.</p>';
    const delegations = [...(agent.delegations_out || []), ...(agent.delegations_in || [])].map((item) => `<article class="registry-delegation"><strong>${escapeHtml(item.source_agent_key)} → ${escapeHtml(item.target_agent_key)}</strong><small>${escapeHtml((item.scope || []).join(" · ") || "General scope")} · ${escapeHtml(item.reason)}</small></article>`).join("") || '<p class="registry-detail-empty">No active delegation.</p>';
    container.innerHTML = `
      <div class="registry-profile-head"><div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.role)} · ${escapeHtml(agent.identity_key)}</p></div><span class="registry-status ${safeClass(agent.availability)}">${escapeHtml(agent.status)} · ${escapeHtml(agent.availability)}</span></div>
      <div class="registry-profile-meta">
        <div><span>Department</span><strong>${escapeHtml(agent.department_key)}</strong></div>
        <div><span>Manager</span><strong>${escapeHtml(agent.manager?.name || "Top-level")}</strong></div>
        <div><span>Runtime</span><strong>${escapeHtml(runtimeName(agent.preferred_runtime_key))}</strong></div>
        <div><span>Clearance</span><strong>${escapeHtml(agent.data_clearance)}</strong></div>
        <div><span>Reliability</span><strong>${Math.round(Number(agent.reliability_score) * 100)}%</strong></div>
        <div><span>Run history</span><strong>${agent.successful_runs} success · ${agent.failed_runs} failed</strong></div>
        <div><span>Version</span><strong>${escapeHtml(agent.version)}</strong></div>
        <div><span>Heartbeat</span><strong>${escapeHtml(formatDateTime(agent.last_heartbeat_at))}</strong></div>
      </div>
      <div class="registry-capacity"><header><strong>Concurrent workload</strong><span>${agent.current_workload} / ${agent.max_concurrency} · ${agent.available_capacity} available</span></header><div class="registry-meter"><i style="width:${utilization}%"></i></div></div>
      <section class="registry-section"><h4>Skills</h4><div class="registry-chips">${(agent.skills || []).map((item) => `<span class="registry-chip">${escapeHtml(item)}</span>`).join("") || '<span class="registry-chip">None</span>'}</div></section>
      <section class="registry-section"><h4>Capabilities</h4><div class="registry-chips">${(agent.capabilities || []).map((item) => `<span class="registry-chip">${escapeHtml(item)}</span>`).join("") || '<span class="registry-chip">None</span>'}</div></section>
      <section class="registry-section"><h4>Allowed tools</h4><div class="registry-chips">${(agent.allowed_tools || []).map((item) => `<span class="registry-chip">${escapeHtml(item)}</span>`).join("") || '<span class="registry-chip">None</span>'}</div></section>
      <section class="registry-section"><h4>Direct reports</h4><div class="registry-report-list">${directReports}</div></section>
      <section class="registry-section"><h4>Active delegation</h4><div class="registry-delegation-list">${delegations}</div></section>
    `;
  }

  function fillFilters() {
    const department = document.querySelector("#registryDepartment");
    const selectedDepartment = department.value;
    const departmentKeys = Object.keys(phase7.stats?.department_distribution || {}).sort();
    department.innerHTML = '<option value="">All departments</option>' + departmentKeys.map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(key.replace("dept:", ""))}</option>`).join("");
    department.value = selectedDepartment;

    const runtime = document.querySelector("#registryRuntime");
    const selectedRuntime = runtime.value;
    runtime.innerHTML = '<option value="">All runtimes</option>' + state.runtimes.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.name)}</option>`).join("");
    runtime.value = selectedRuntime;

    const skill = document.querySelector("#registrySkill");
    const selectedSkill = skill.value;
    skill.innerHTML = '<option value="">All skills</option>' + phase7.skills.map((item) => `<option value="${escapeHtml(item.skill)}">${escapeHtml(item.skill)} (${item.agent_count})</option>`).join("");
    skill.value = selectedSkill;
  }

  async function loadAgents() {
    const params = new URLSearchParams();
    const fields = {
      query: document.querySelector("#registrySearch")?.value.trim(),
      department_key: document.querySelector("#registryDepartment")?.value,
      runtime_key: document.querySelector("#registryRuntime")?.value,
      availability: document.querySelector("#registryAvailability")?.value,
      skill: document.querySelector("#registrySkill")?.value,
    };
    Object.entries(fields).forEach(([key, value]) => { if (value) params.set(key, value); });
    phase7.agents = await operatorApi(`/api/registry/agents?${params.toString()}`, {}, true);
    if (phase7.selected && !phase7.agents.some((item) => item.key === phase7.selected.key)) phase7.selected = null;
    renderDirectory();
    renderDetail();
  }

  async function loadRegistry(silent = false) {
    if (!silent) document.querySelector("#registryState").textContent = "Loading";
    try {
      const [stats, organization, skills, delegations] = await Promise.all([
        operatorApi("/api/registry/stats", {}, true),
        operatorApi("/api/registry/organization", {}, true),
        operatorApi("/api/registry/skills", {}, true),
        operatorApi("/api/registry/delegations?status=ACTIVE", {}, true),
      ]);
      phase7.stats = stats;
      phase7.organization = organization;
      phase7.skills = skills;
      phase7.delegations = delegations;
      renderStats();
      fillFilters();
      await loadAgents();
      if (phase7.selected) phase7.selected = await operatorApi(`/api/registry/agents/${encodeURIComponent(phase7.selected.key)}`, {}, true);
      renderDetail();
      document.querySelector("#registryState").textContent = "Live";
    } catch (error) {
      document.querySelector("#registryState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function selectAgent(key) {
    phase7.selected = await operatorApi(`/api/registry/agents/${encodeURIComponent(key)}`, {}, true);
    renderDirectory();
    renderDetail();
  }

  function openAgentDialog() {
    document.querySelector("#registryAgentForm").reset();
    document.querySelector("#newAgentDepartment").innerHTML = Object.keys(phase7.stats?.department_distribution || {}).sort().map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(key.replace("dept:", ""))}</option>`).join("");
    document.querySelector("#newAgentManager").innerHTML = '<option value="">No manager</option>' + phase7.agents.map((agent) => `<option value="${escapeHtml(agent.key)}">${escapeHtml(agent.name)} · ${escapeHtml(agent.role)}</option>`).join("");
    document.querySelector("#newAgentRuntime").innerHTML = state.runtimes.map((runtime) => `<option value="${escapeHtml(runtime.key)}">${escapeHtml(runtime.name)}</option>`).join("");
    document.querySelector("#registryAgentFormMessage").textContent = "Agent creation also registers a governed AGENT identity.";
    document.querySelector("#registryAgentDialog").showModal();
  }

  async function createAgent(event) {
    event.preventDefault();
    const key = document.querySelector("#newAgentKey").value.trim();
    const message = document.querySelector("#registryAgentFormMessage");
    message.textContent = "Registering agent…";
    try {
      phase7.selected = await operatorApi("/api/registry/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_key: key,
          identity_key: document.querySelector("#newAgentIdentity").value.trim(),
          display_name: document.querySelector("#newAgentName").value.trim(),
          role_title: document.querySelector("#newAgentRole").value.trim(),
          department_key: document.querySelector("#newAgentDepartment").value,
          manager_agent_key: document.querySelector("#newAgentManager").value || null,
          preferred_runtime_key: document.querySelector("#newAgentRuntime").value,
          max_concurrency: Number(document.querySelector("#newAgentConcurrency").value),
          skills: lines(document.querySelector("#newAgentSkills").value),
          capabilities: lines(document.querySelector("#newAgentCapabilities").value),
          allowed_tools: lines(document.querySelector("#newAgentTools").value),
          data_clearance: document.querySelector("#newAgentClearance").value,
          version: document.querySelector("#newAgentVersion").value.trim(),
          owner_identity: localStorage.getItem("beezaIdentity") || "human:owner",
          profile: { registered_from: "command-center" },
        }),
      });
      message.textContent = `${key} registered.`;
      setTimeout(() => document.querySelector("#registryAgentDialog").close(), 650);
      await loadRegistry(true);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function openDelegationDialog() {
    const agent = phase7.selected;
    if (!agent) return;
    const options = phase7.agents.filter((item) => item.status === "ACTIVE").map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.name)} · ${escapeHtml(item.role)}</option>`).join("");
    document.querySelector("#delegationSource").innerHTML = options;
    document.querySelector("#delegationTarget").innerHTML = options;
    document.querySelector("#delegationSource").value = agent.key;
    const target = phase7.agents.find((item) => item.key !== agent.key && item.status === "ACTIVE");
    if (target) document.querySelector("#delegationTarget").value = target.key;
    document.querySelector("#delegationScope").value = "mission:coordinate\nreport:review";
    document.querySelector("#delegationReason").value = "Temporary delegation under the active chain of command.";
    document.querySelector("#registryDelegationMessage").textContent = `${agent.name} is the delegation source.`;
    document.querySelector("#registryDelegationDialog").showModal();
  }

  async function createDelegation(event) {
    event.preventDefault();
    const message = document.querySelector("#registryDelegationMessage");
    message.textContent = "Creating delegation…";
    try {
      const ends = document.querySelector("#delegationEnds").value;
      await operatorApi("/api/registry/delegations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_agent_key: document.querySelector("#delegationSource").value,
          target_agent_key: document.querySelector("#delegationTarget").value,
          scope: lines(document.querySelector("#delegationScope").value),
          reason: document.querySelector("#delegationReason").value.trim(),
          ends_at: ends ? new Date(ends).toISOString() : null,
        }),
      });
      message.textContent = "Delegation created.";
      setTimeout(() => document.querySelector("#registryDelegationDialog").close(), 650);
      await loadRegistry(true);
      if (phase7.selected) await selectAgent(phase7.selected.key);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  async function agentAction(action) {
    const agent = phase7.selected;
    if (!agent) return;
    try {
      if (action === "delegate") {
        openDelegationDialog();
        return;
      }
      if (action === "heartbeat") {
        phase7.selected = await operatorApi(`/api/registry/agents/${encodeURIComponent(agent.key)}/heartbeat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ availability: agent.current_workload ? "BUSY" : "AVAILABLE", current_workload: agent.current_workload }),
        });
        showMessage(`${agent.name} heartbeat recorded.`, "success");
      } else if (action === "status") {
        const status = agent.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE";
        if (status === "SUSPENDED" && !window.confirm(`Suspend ${agent.name}? Governed mutations from this agent identity will be blocked.`)) return;
        phase7.selected = await operatorApi(`/api/registry/agents/${encodeURIComponent(agent.key)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, availability: status === "ACTIVE" ? "AVAILABLE" : "OFFLINE" }),
        });
        showMessage(`${agent.name} changed to ${status}.`, "success");
      }
      await loadRegistry(true);
      await selectAgent(agent.key);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function reconcileRegistry() {
    try {
      const result = await operatorApi("/api/registry/reconcile", { method: "POST" });
      showMessage(`Reconciled ${result.registered_agents} agents and ${result.active_tasks} active tasks; ${result.changed_agents} profiles changed.`, "success");
      await loadRegistry(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function startPolling() {
    if (phase7.timer) clearInterval(phase7.timer);
    phase7.timer = setInterval(() => {
      if (!document.hidden) void loadRegistry(true);
    }, 15000);
  }

  async function initialize() {
    if (phase7.initialized) return;
    phase7.initialized = true;
    installUi();
    startPolling();
    await loadRegistry();
  }

  void initialize();
})();
