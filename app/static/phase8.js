(() => {
  const phase8 = {
    status: null,
    pool: [],
    decisions: [],
    selected: null,
    initialized: false,
    timer: null,
  };

  function lines(value) {
    return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function installUi() {
    if (document.querySelector("#schedulerRouter")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "schedulerNav";
    nav.innerHTML = 'Scheduler <span id="schedulerNavCount">0</span>';
    document.querySelector("#registryNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel scheduler-panel";
    panel.id = "schedulerRouter";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 8 · SCHEDULER & INTELLIGENT ROUTER</p><h2>Agent and Runtime Routing</h2></div>
        <div class="scheduler-header-state"><span id="schedulerState">Starting</span><b id="schedulerCount">0</b></div>
      </div>
      <p class="dispatch-intro">Route work by skill, capability, tool access, clearance, reliability, available concurrency, runtime health, latency, cost and deadline. Failed routes can exclude the previous agent/runtime and fail over automatically.</p>
      <div class="scheduler-toolbar">
        <span id="schedulerPolicySummary">Loading routing policy…</span>
        <div class="scheduler-toolbar-actions"><button class="secondary" id="schedulerTick">Run scheduler</button><button class="secondary" id="schedulerSimulate">Simulate route</button><button class="primary" id="schedulerNewTask">+ Smart task</button></div>
      </div>
      <div id="schedulerStats" class="scheduler-stats"></div>
      <div id="schedulerRuntimePool" class="scheduler-runtime-pool"></div>
      <div class="scheduler-layout">
        <section class="scheduler-box">
          <div class="scheduler-box-head"><div><strong>Routing decisions</strong><small>Selected, waiting and exhausted routes</small></div><span id="schedulerDecisionFilter">Current mission</span></div>
          <div id="schedulerDecisionList" class="scheduler-decision-list"></div>
        </section>
        <section class="scheduler-box">
          <div class="scheduler-box-head"><div><strong>Decision evidence</strong><small>Candidate score components and rejection reasons</small></div><div id="schedulerDetailActions"></div></div>
          <div id="schedulerDetail" class="scheduler-detail"><p class="scheduler-empty">Select a routing decision.</p></div>
        </section>
      </div>
    `;
    document.querySelector("#agentRegistry")?.after(panel);

    const taskDialog = document.createElement("dialog");
    taskDialog.id = "schedulerTaskDialog";
    taskDialog.innerHTML = `
      <form method="dialog" id="schedulerTaskForm">
        <div class="dialog-head"><div><p class="eyebrow">INTELLIGENT WORK ROUTING</p><h2>Create Smart Task</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="scheduler-form-grid">
          <label class="full">Task title<input id="smartTaskTitle" required minlength="3" placeholder="Investigate intermittent storage latency" /></label>
          <label class="full">Objective<textarea id="smartTaskObjective" required minlength="10" placeholder="Analyze current evidence, identify the most likely cause and return a verified remediation recommendation."></textarea></label>
          <label>Priority<select id="smartTaskPriority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select></label>
          <label>Review policy<select id="smartTaskReview"><option>AUTO</option><option>HUMAN</option></select></label>
          <label>Required clearance<select id="smartTaskClearance"><option>PUBLIC</option><option selected>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label>Preferred department<select id="smartTaskDepartment"><option value="">Any department</option></select></label>
          <label>Preferred runtime<select id="smartTaskRuntime"><option value="">Any runtime</option></select></label>
          <label>Estimated tokens<input id="smartTaskTokens" type="number" min="1" max="10000000" value="4000" /></label>
          <label>Maximum cost USD<input id="smartTaskCost" type="number" min="0" step="0.001" placeholder="No ceiling" /></label>
          <label>Deadline<input id="smartTaskDeadline" type="datetime-local" /></label>
          <label class="full">Required skills<textarea id="smartTaskSkills" placeholder="incident-response\nstorage\nmetrics"></textarea></label>
          <label class="full">Required capabilities<textarea id="smartTaskCapabilities" placeholder="root-cause-analysis\nremediation-plan"></textarea></label>
          <label class="full">Required tools<textarea id="smartTaskTools" placeholder="prometheus\nrunbook"></textarea></label>
          <label class="full">Expected outputs<textarea id="smartTaskOutputs" placeholder="Root cause analysis\nRemediation recommendation\nVerification evidence"></textarea></label>
          <label class="full">Acceptance criteria<textarea id="smartTaskCriteria" placeholder="Evidence supports the conclusion\nRollback risk is stated"></textarea></label>
        </div>
        <div class="scheduler-checks"><label><input id="smartTaskStrict" type="checkbox" /> Strict skill/tool match</label><label><input id="smartTaskOverflow" type="checkbox" /> Allow capacity overflow</label></div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Route and dispatch</button></div>
        <p id="schedulerTaskMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(taskDialog);

    const simulateDialog = document.createElement("dialog");
    simulateDialog.id = "schedulerSimulateDialog";
    simulateDialog.innerHTML = `
      <form method="dialog" id="schedulerSimulateForm">
        <div class="dialog-head"><div><p class="eyebrow">DRY RUN</p><h2>Simulate Routing</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="scheduler-form-grid">
          <label class="full">Objective<textarea id="simulateObjective" required minlength="5" placeholder="Choose the best agent for a Thai-language infrastructure capacity analysis."></textarea></label>
          <label>Priority<select id="simulatePriority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select></label>
          <label>Clearance<select id="simulateClearance"><option>PUBLIC</option><option selected>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label>Department<select id="simulateDepartment"><option value="">Any department</option></select></label>
          <label>Runtime<select id="simulateRuntime"><option value="">Any runtime</option></select></label>
          <label>Tokens<input id="simulateTokens" type="number" min="1" value="4000" /></label>
          <label>Maximum cost USD<input id="simulateCost" type="number" min="0" step="0.001" /></label>
          <label class="full">Skills<textarea id="simulateSkills" placeholder="capacity-planning\nforecasting"></textarea></label>
          <label class="full">Capabilities<textarea id="simulateCapabilities" placeholder="analysis\nexecutive-report"></textarea></label>
          <label class="full">Tools<textarea id="simulateTools" placeholder="sql\nmetrics"></textarea></label>
        </div>
        <div class="scheduler-checks"><label><input id="simulateStrict" type="checkbox" /> Strict match</label><label><input id="simulateOverflow" type="checkbox" /> Allow overflow</label></div>
        <div id="schedulerSimulationResult" class="scheduler-simulation-result">No simulation run.</div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Close</button><button type="submit" value="default" class="primary">Run simulation</button></div>
      </form>
    `;
    document.body.append(simulateDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#schedulerTick").addEventListener("click", runTick);
    panel.querySelector("#schedulerNewTask").addEventListener("click", openTaskDialog);
    panel.querySelector("#schedulerSimulate").addEventListener("click", openSimulationDialog);
    taskDialog.querySelector("#schedulerTaskForm").addEventListener("submit", createSmartTask);
    simulateDialog.querySelector("#schedulerSimulateForm").addEventListener("submit", simulateRoute);
  }

  function fillSelectors() {
    const departments = Object.keys(phase7Stats()?.department_distribution || {}).sort();
    ["#smartTaskDepartment", "#simulateDepartment"].forEach((selector) => {
      const node = document.querySelector(selector);
      const previous = node.value;
      node.innerHTML = '<option value="">Any department</option>' + departments.map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(key.replace("dept:", ""))}</option>`).join("");
      node.value = previous;
    });
    ["#smartTaskRuntime", "#simulateRuntime"].forEach((selector) => {
      const node = document.querySelector(selector);
      const previous = node.value;
      node.innerHTML = '<option value="">Any runtime</option>' + state.runtimes.map((runtime) => `<option value="${escapeHtml(runtime.key)}">${escapeHtml(runtime.name)}</option>`).join("");
      node.value = previous;
    });
  }

  function phase7Stats() {
    const registered = Number(document.querySelector("#registryCount")?.textContent || 0);
    const departments = {};
    document.querySelectorAll("#registryDepartment option[value]").forEach((option) => { if (option.value) departments[option.value] = 1; });
    return { registered_agents: registered, department_distribution: departments };
  }

  function renderStats() {
    const stats = phase8.status?.stats || {};
    const worker = phase8.status?.worker || {};
    const decisions = stats.decisions || {};
    const cards = [
      ["Awaiting route", stats.awaiting_route || 0, `Worker ${worker.status || "starting"}`],
      ["Selected", decisions.SELECTED || 0, `Average score ${Math.round(Number(stats.average_selected_score || 0) * 100)}%`],
      ["Waiting", decisions.WAITING || 0, `${worker.last_waiting || 0} last tick`],
      ["No route", decisions.NO_ROUTE || 0, `${worker.last_blocked || 0} last tick`],
      ["Runtime slots", stats.runtime_available || 0, `${stats.runtime_active || 0}/${stats.runtime_capacity || 0} active`],
      ["Online runtimes", stats.online_runtimes || 0, `${stats.configured_runtimes || 0} configured`],
    ];
    document.querySelector("#schedulerStats").innerHTML = cards.map(([label, value, detail]) => `<article class="scheduler-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
    document.querySelector("#schedulerCount").textContent = String(stats.awaiting_route || 0);
    document.querySelector("#schedulerNavCount").textContent = String((stats.awaiting_route || 0) + (decisions.WAITING || 0));
    const policy = stats.policy || {};
    document.querySelector("#schedulerPolicySummary").textContent = `${policy.name || "Balanced Agent Router"} · minimum score ${Math.round(Number(policy.minimum_score || 0) * 100)}% · skill coverage ${Math.round(Number(policy.minimum_skill_coverage || 0) * 100)}% · retry ${policy.retry_seconds || 30}s`;
    document.querySelector("#schedulerState").textContent = worker.status || "starting";
  }

  function renderRuntimePool() {
    const container = document.querySelector("#schedulerRuntimePool");
    container.innerHTML = phase8.pool.map((runtime) => {
      const utilization = Math.min(100, Math.round(Number(runtime.utilization || 0) * 100));
      return `<article class="scheduler-runtime-card"><header><div><strong>${escapeHtml(runtime.name)}</strong><small>${escapeHtml(runtime.runtime_key)} · ${escapeHtml(runtime.model || "default model")}</small></div><span class="scheduler-status ${safeClass(runtime.status)}">${escapeHtml(runtime.status)}</span></header><p>${runtime.active_dispatches}/${runtime.capacity_limit} active · ${runtime.available_slots} available<br />Latency ${runtime.latency_ms === null || runtime.latency_ms === undefined ? "—" : `${Math.round(runtime.latency_ms)} ms`} · $${Number(runtime.cost_per_1k_tokens_usd || 0).toFixed(3)}/1k tokens</p><div class="scheduler-meter"><i style="width:${utilization}%"></i></div></article>`;
    }).join("") || '<p class="scheduler-empty">No runtime pool information.</p>';
  }

  function renderDecisionList() {
    const container = document.querySelector("#schedulerDecisionList");
    if (!phase8.decisions.length) {
      container.innerHTML = '<p class="scheduler-empty">No routing decisions for this mission.</p>';
      return;
    }
    container.innerHTML = phase8.decisions.map((decision) => `
      <button class="scheduler-decision-card ${phase8.selected?.key === decision.key ? "active" : ""}" data-scheduler-decision="${escapeHtml(decision.key)}">
        <header><div><strong>${escapeHtml(decision.task_key || "Simulation")}</strong><small>${escapeHtml(decision.key)} · attempt ${decision.attempt}</small></div><span class="scheduler-status ${safeClass(decision.status)}">${escapeHtml(decision.status)}</span></header>
        <p>${escapeHtml(decision.reason)}</p>
        <footer><span>${escapeHtml(decision.selected_agent_key || "No agent")}</span><span>${decision.selected_score === null || decision.selected_score === undefined ? "—" : `${Math.round(Number(decision.selected_score) * 100)}%`} · ${escapeHtml(formatDateTime(decision.created_at))}</span></footer>
      </button>
    `).join("");
    container.querySelectorAll("[data-scheduler-decision]").forEach((button) => button.addEventListener("click", () => {
      phase8.selected = phase8.decisions.find((item) => item.key === button.dataset.schedulerDecision) || null;
      renderDecisionList();
      renderDecisionDetail();
    }));
  }

  function renderDecisionDetail() {
    const container = document.querySelector("#schedulerDetail");
    const actions = document.querySelector("#schedulerDetailActions");
    const decision = phase8.selected;
    if (!decision) {
      actions.innerHTML = "";
      container.innerHTML = '<p class="scheduler-empty">Select a routing decision.</p>';
      return;
    }
    actions.innerHTML = decision.task_key ? `<button class="secondary" id="schedulerReroute">Reroute task</button>` : "";
    actions.querySelector("#schedulerReroute")?.addEventListener("click", () => rerouteTask(decision.task_key));
    const request = decision.requested || {};
    const candidates = (decision.candidates || []).map((candidate, index) => {
      const components = Object.entries(candidate.components || {}).map(([name, score]) => `<span>${escapeHtml(name)} ${Math.round(Number(score) * 100)}%</span>`).join("");
      const explanation = candidate.accepted ? (candidate.reasons || []).join(" · ") : (candidate.rejections || []).join(" · ");
      return `<article class="scheduler-candidate ${candidate.accepted ? "" : "rejected"}"><header><div><strong>#${index + 1} ${escapeHtml(candidate.name)} · ${escapeHtml(candidate.role)}</strong><small>${escapeHtml(candidate.agent_key)} · ${escapeHtml(candidate.runtime_name)} · cost $${Number(candidate.estimated_cost_usd || 0).toFixed(4)}</small></div><span class="scheduler-score">${Math.round(Number(candidate.score || 0) * 100)}%</span></header><p>${escapeHtml(explanation || "No explanation")}</p><div class="scheduler-score-line">${components}</div></article>`;
    }).join("") || '<p class="scheduler-empty">No candidate evidence was retained.</p>';
    container.innerHTML = `
      <div class="scheduler-detail-title"><div><h3>${escapeHtml(decision.selected_agent_key || "No route selected")}</h3><p>${escapeHtml(decision.reason)}</p></div><span class="scheduler-status ${safeClass(decision.status)}">${escapeHtml(decision.status)}</span></div>
      <div class="scheduler-detail-meta">
        <div><span>Task</span><strong>${escapeHtml(decision.task_key || "Simulation")}</strong></div>
        <div><span>Runtime</span><strong>${escapeHtml(decision.selected_runtime_key || "—")}</strong></div>
        <div><span>Model</span><strong>${escapeHtml(decision.selected_model || "default")}</strong></div>
        <div><span>Score</span><strong>${decision.selected_score === null || decision.selected_score === undefined ? "—" : `${Math.round(Number(decision.selected_score) * 100)}%`}</strong></div>
      </div>
      <div class="scheduler-request"><strong>Routing request</strong><p>Skills: ${escapeHtml((request.required_skills || []).join(", ") || "none")}\nCapabilities: ${escapeHtml((request.required_capabilities || []).join(", ") || "none")}\nTools: ${escapeHtml((request.required_tools || []).join(", ") || "none")}\nClearance: ${escapeHtml(request.required_clearance || "INTERNAL")} · Preferred runtime: ${escapeHtml(request.preferred_runtime_key || "any")} · Cost ceiling: ${request.maximum_cost_usd === null || request.maximum_cost_usd === undefined ? "none" : `$${Number(request.maximum_cost_usd).toFixed(4)}`}</p></div>
      <div class="scheduler-candidates"><h4>Candidate ranking</h4>${candidates}</div>
    `;
  }

  function render() {
    renderStats();
    renderRuntimePool();
    renderDecisionList();
    renderDecisionDetail();
  }

  async function loadScheduler(silent = false) {
    if (!silent) document.querySelector("#schedulerState").textContent = "Loading";
    try {
      const missionKey = state.selectedMission?.key;
      const query = missionKey ? `?mission_key=${encodeURIComponent(missionKey)}&limit=200` : "?limit=200";
      const [status, pool, decisions] = await Promise.all([
        operatorApi("/api/scheduler/status", {}, true),
        operatorApi("/api/scheduler/runtime-pool", {}, true),
        operatorApi(`/api/scheduler/decisions${query}`, {}, true),
      ]);
      phase8.status = status;
      phase8.pool = pool;
      phase8.decisions = decisions;
      if (phase8.selected) phase8.selected = decisions.find((item) => item.key === phase8.selected.key) || null;
      document.querySelector("#schedulerDecisionFilter").textContent = missionKey || "All missions";
      fillSelectors();
      render();
    } catch (error) {
      document.querySelector("#schedulerState").textContent = "Access denied";
      if (!silent) document.querySelector("#schedulerPolicySummary").textContent = error.message;
    }
  }

  function openTaskDialog() {
    const mission = state.selectedMission;
    if (!mission) {
      window.alert("Select a mission before creating a smart task.");
      return;
    }
    document.querySelector("#schedulerTaskForm").reset();
    document.querySelector("#smartTaskPriority").value = mission.priority || "NORMAL";
    document.querySelector("#smartTaskTokens").value = "4000";
    document.querySelector("#schedulerTaskMessage").textContent = `Mission ${mission.key} · scheduler will choose the agent, runtime and model.`;
    fillSelectors();
    document.querySelector("#schedulerTaskDialog").showModal();
  }

  async function createSmartTask(event) {
    event.preventDefault();
    const mission = state.selectedMission;
    if (!mission) return;
    const deadline = document.querySelector("#smartTaskDeadline").value;
    const costText = document.querySelector("#smartTaskCost").value;
    const message = document.querySelector("#schedulerTaskMessage");
    message.textContent = "Scoring candidates and dispatching…";
    try {
      const task = await operatorApi(`/api/missions/${encodeURIComponent(mission.key)}/routed-tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.querySelector("#smartTaskTitle").value.trim(),
          objective: document.querySelector("#smartTaskObjective").value.trim(),
          source_identity: localStorage.getItem("beezaIdentity") || `agent:${mission.commander}`,
          priority: document.querySelector("#smartTaskPriority").value,
          review_policy: document.querySelector("#smartTaskReview").value,
          auto_dispatch: true,
          routing_mode: "FAILOVER",
          required_skills: lines(document.querySelector("#smartTaskSkills").value),
          required_capabilities: lines(document.querySelector("#smartTaskCapabilities").value),
          required_tools: lines(document.querySelector("#smartTaskTools").value),
          required_clearance: document.querySelector("#smartTaskClearance").value,
          preferred_department: document.querySelector("#smartTaskDepartment").value || null,
          preferred_runtime_key: document.querySelector("#smartTaskRuntime").value || null,
          maximum_cost_usd: costText === "" ? null : Number(costText),
          estimated_tokens: Number(document.querySelector("#smartTaskTokens").value || 4000),
          strict_skills: document.querySelector("#smartTaskStrict").checked,
          allow_overflow: document.querySelector("#smartTaskOverflow").checked,
          expected_outputs: lines(document.querySelector("#smartTaskOutputs").value),
          acceptance_criteria: lines(document.querySelector("#smartTaskCriteria").value),
          deadline_at: deadline ? new Date(deadline).toISOString() : null,
          context: { created_from: "phase8-command-center" },
        }),
      });
      message.textContent = `${task.key} · ${task.target_identity} · ${task.target_runtime_key} · ${task.status}`;
      setTimeout(() => document.querySelector("#schedulerTaskDialog").close(), 800);
      await loadScheduler(true);
      if (typeof loadCollaboration === "function") await loadCollaboration(mission.key, true);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function openSimulationDialog() {
    document.querySelector("#schedulerSimulateForm").reset();
    document.querySelector("#simulateTokens").value = "4000";
    document.querySelector("#schedulerSimulationResult").textContent = "No simulation run.";
    fillSelectors();
    document.querySelector("#schedulerSimulateDialog").showModal();
  }

  async function simulateRoute(event) {
    event.preventDefault();
    const resultNode = document.querySelector("#schedulerSimulationResult");
    const costText = document.querySelector("#simulateCost").value;
    resultNode.textContent = "Scoring current registry and runtime capacity…";
    try {
      const result = await operatorApi("/api/scheduler/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          objective: document.querySelector("#simulateObjective").value.trim(),
          priority: document.querySelector("#simulatePriority").value,
          required_skills: lines(document.querySelector("#simulateSkills").value),
          required_capabilities: lines(document.querySelector("#simulateCapabilities").value),
          required_tools: lines(document.querySelector("#simulateTools").value),
          required_clearance: document.querySelector("#simulateClearance").value,
          preferred_department: document.querySelector("#simulateDepartment").value || null,
          preferred_runtime_key: document.querySelector("#simulateRuntime").value || null,
          maximum_cost_usd: costText === "" ? null : Number(costText),
          estimated_tokens: Number(document.querySelector("#simulateTokens").value || 4000),
          strict_skills: document.querySelector("#simulateStrict").checked,
          allow_overflow: document.querySelector("#simulateOverflow").checked,
        }),
      });
      const selected = result.selected;
      resultNode.innerHTML = selected ? `<strong>${escapeHtml(selected.name)} → ${escapeHtml(selected.runtime_name)}</strong><br />Score ${Math.round(Number(selected.score) * 100)}% · cost $${Number(selected.estimated_cost_usd || 0).toFixed(4)} · ${selected.available_capacity} agent slots · ${selected.runtime_available_slots} runtime slots<br />${escapeHtml((selected.reasons || []).join(" · "))}` : `No eligible route. Top rejection: ${escapeHtml((result.candidates?.[0]?.rejections || ["No candidates"]).join(" · "))}`;
    } catch (error) {
      resultNode.textContent = error.message;
    }
  }

  async function rerouteTask(taskKey) {
    if (!taskKey) return;
    if (!window.confirm(`Exclude the current selection and reroute ${taskKey}?`)) return;
    try {
      const result = await operatorApi(`/api/scheduler/tasks/${encodeURIComponent(taskKey)}/route`, { method: "POST" });
      document.querySelector("#schedulerPolicySummary").textContent = result.decision ? result.decision.reason : "Task is already being routed by another scheduler worker.";
      await loadScheduler(true);
    } catch (error) {
      document.querySelector("#schedulerPolicySummary").textContent = error.message;
    }
  }

  async function runTick() {
    const button = document.querySelector("#schedulerTick");
    button.disabled = true;
    try {
      const result = await operatorApi("/api/scheduler/tick", { method: "POST" });
      document.querySelector("#schedulerPolicySummary").textContent = `Scheduler tick: ${result.routed} routed · ${result.waiting} waiting · ${result.blocked} blocked.`;
      await loadScheduler(true);
    } catch (error) {
      document.querySelector("#schedulerPolicySummary").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  function extendMissionSelection() {
    const previousSelectMission = selectMission;
    selectMission = async function selectMissionWithScheduler(key) {
      await previousSelectMission(key);
      phase8.selected = null;
      await loadScheduler(true);
    };
  }

  function startPolling() {
    if (phase8.timer) clearInterval(phase8.timer);
    phase8.timer = setInterval(() => {
      if (!document.hidden) void loadScheduler(true);
    }, 5000);
  }

  async function initialize() {
    if (phase8.initialized) return;
    phase8.initialized = true;
    installUi();
    extendMissionSelection();
    startPolling();
    await loadScheduler();
  }

  void initialize();
})();
