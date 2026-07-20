(() => {
  const phase4 = {
    missionKey: null,
    tasks: [],
    messages: [],
    stats: {},
    timer: null,
    initialized: false,
  };

  function installUi() {
    if (document.querySelector("#collaborationBus")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "collaborationNav";
    nav.innerHTML = 'Collaboration <span id="collaborationNavCount">0</span>';
    document.querySelector("#runtimeEventsNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel collaboration-panel";
    panel.id = "collaborationBus";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 4 · COLLABORATION BUS</p><h2>Cross-runtime Work Handoffs</h2></div>
        <div class="collaboration-header-state"><span id="collaborationState">Ready</span><b id="collaborationTaskCount">0</b></div>
      </div>
      <p class="dispatch-intro">Agents can assign typed work packages, wait on dependencies, send results, request revisions, follow up automatically and escalate stalled work across OpenClaw, CherryAgent, Hermes and thClaws.</p>
      <div class="collaboration-worker"><span>Collaboration worker</span><strong id="collaborationWorkerState">Starting</strong></div>
      <div id="collaborationStats" class="collaboration-stats"></div>
      <div class="collaboration-layout">
        <div class="collaboration-tasks">
          <div class="collaboration-section-head"><div><strong>Mission work graph</strong><small>Typed handoffs and dependencies</small></div><div><button class="secondary" id="collaborationTick">Run tick</button> <button class="primary" id="newHandoff">+ New handoff</button></div></div>
          <div id="collaborationBoard" class="collaboration-board"></div>
        </div>
        <aside class="collaboration-mailbox">
          <div class="collaboration-section-head"><div><strong>Mission mailbox</strong><small>Assignments, follow-ups and responses</small></div></div>
          <div id="collaborationMessages" class="collaboration-message-list"></div>
        </aside>
      </div>
    `;
    document.querySelector("#runtimeEventStream")?.after(panel);

    const dialog = document.createElement("dialog");
    dialog.id = "handoffDialog";
    dialog.innerHTML = `
      <form method="dialog" id="handoffForm">
        <div class="dialog-head"><div><p class="eyebrow">BEEZA COLLABORATION BUS</p><h2>Create Cross-runtime Handoff</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="handoff-grid">
          <label>Target runtime<select id="handoffRuntime" required></select></label>
          <label>Target identity<input id="handoffTarget" placeholder="runtime target or agent role" /></label>
          <label class="full">Task title<input id="handoffTitle" required minlength="3" placeholder="Analyze storage evidence" /></label>
          <label class="full">Objective<textarea id="handoffObjective" required minlength="10" placeholder="Review the evidence, identify the most likely root cause and return an evidence-backed recommendation."></textarea></label>
          <label>Priority<select id="handoffPriority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select></label>
          <label>Review policy<select id="handoffReview"><option>AUTO</option><option>HUMAN</option></select></label>
          <label class="full">Depends on task keys<input id="handoffDepends" placeholder="TASK-AAA, TASK-BBB" /></label>
          <label class="full">Expected outputs<textarea id="handoffOutputs" placeholder="root cause\nevidence links\nrecommended action"></textarea></label>
          <label class="full">Acceptance criteria<textarea id="handoffCriteria" placeholder="At least two evidence sources\nConfidence score included"></textarea></label>
          <label class="handoff-check full"><input type="checkbox" id="handoffAuto" checked /> Dispatch automatically when dependencies are complete</label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create handoff</button></div>
        <p id="handoffMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(dialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#newHandoff").addEventListener("click", openHandoffDialog);
    panel.querySelector("#collaborationTick").addEventListener("click", runTick);
    dialog.querySelector("#handoffForm").addEventListener("submit", createHandoff);
  }

  function lines(value) {
    return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function taskResult(task) {
    const result = task.result || {};
    return result.summary || result.error || result.blocker || result.note || "";
  }

  function renderStats() {
    const stats = phase4.stats || {};
    const cards = [
      ["Total", stats.total || 0],
      ["Running", stats.running || 0],
      ["Waiting", stats.waiting || 0],
      ["Blocked", stats.blocked || 0],
      ["Completed", stats.completed || 0],
    ];
    const container = document.querySelector("#collaborationStats");
    if (container) container.innerHTML = cards.map(([label, value]) => `<article class="collaboration-stat"><span>${label}</span><strong>${value}</strong></article>`).join("");
    document.querySelector("#collaborationTaskCount").textContent = String(stats.total || 0);
    document.querySelector("#collaborationNavCount").textContent = String((stats.running || 0) + (stats.waiting || 0) + (stats.blocked || 0));
  }

  function taskActions(task) {
    if (["BLOCKED", "FAILED", "ESCALATED"].includes(task.status)) {
      return `<button class="primary" data-task-action="retry" data-task-key="${escapeHtml(task.key)}">Retry</button>`;
    }
    if (task.status === "REVIEW") {
      return `<button class="primary" data-task-review="accept" data-task-key="${escapeHtml(task.key)}">Accept</button><button class="secondary" data-task-review="revise" data-task-key="${escapeHtml(task.key)}">Revise</button><button class="danger-button" data-task-review="reject" data-task-key="${escapeHtml(task.key)}">Reject</button>`;
    }
    if (task.status === "QUEUED" && !task.auto_dispatch) {
      return `<button class="primary" data-task-action="accept" data-task-key="${escapeHtml(task.key)}">Dispatch</button>`;
    }
    if (["RUNNING", "DISPATCHING", "WAITING_APPROVAL"].includes(task.status)) {
      return `<button class="danger-button" data-task-action="block" data-task-key="${escapeHtml(task.key)}">Mark blocked</button>`;
    }
    return "";
  }

  function renderTasks() {
    const board = document.querySelector("#collaborationBoard");
    if (!board) return;
    if (!phase4.tasks.length) {
      board.innerHTML = '<p class="collaboration-empty">No handoffs yet. Create a typed work package and assign it to another runtime.</p>';
      return;
    }
    board.innerHTML = phase4.tasks.map((task) => {
      const statusClass = safeClass(task.status);
      const dependencies = task.depends_on?.length ? task.depends_on.join(", ") : "none";
      const result = taskResult(task);
      return `
        <article class="collaboration-task-card ${statusClass}">
          <header><div><h3>${escapeHtml(task.title)}</h3><small>${escapeHtml(task.key)} · ${escapeHtml(task.source_identity)} → ${escapeHtml(task.target_identity)}</small></div><span class="collaboration-status ${statusClass}">${escapeHtml(task.status)}</span></header>
          <p class="collaboration-objective">${escapeHtml(task.objective)}</p>
          <div class="collaboration-route"><span>${escapeHtml(runtimeName(task.target_runtime_key))}</span><span>${escapeHtml(task.priority)}</span><span>Review ${escapeHtml(task.review_policy)}</span><span>Dependencies ${escapeHtml(dependencies)}</span></div>
          <div class="collaboration-task-meta"><span>Attempts ${task.attempts}</span><span>Follow-ups ${task.follow_up_count}</span><span>Updated ${escapeHtml(formatDateTime(task.updated_at))}</span>${task.dispatch_key ? `<span>${escapeHtml(task.dispatch_key)}</span>` : ""}</div>
          ${result ? `<div class="collaboration-task-result">${escapeHtml(result)}</div>` : ""}
          <div class="collaboration-actions">${taskActions(task)}</div>
        </article>
      `;
    }).join("");

    board.querySelectorAll("[data-task-action]").forEach((button) => button.addEventListener("click", () => taskAction(button.dataset.taskKey, button.dataset.taskAction)));
    board.querySelectorAll("[data-task-review]").forEach((button) => button.addEventListener("click", () => reviewTask(button.dataset.taskKey, button.dataset.taskReview)));
  }

  function renderMessages() {
    const container = document.querySelector("#collaborationMessages");
    if (!container) return;
    if (!phase4.messages.length) {
      container.innerHTML = '<p class="collaboration-empty">No collaboration messages yet.</p>';
      return;
    }
    container.innerHTML = phase4.messages.slice(0, 100).map((message) => `
      <article class="collaboration-message">
        <header><strong>${escapeHtml(message.subject)}</strong><span>${escapeHtml(message.type)}</span></header>
        <small>${escapeHtml(message.source_identity)} → ${escapeHtml(message.target_identity)} · ${escapeHtml(message.status)} · ${escapeHtml(formatDateTime(message.created_at))}</small>
        <p>${escapeHtml(message.body)}</p>
      </article>
    `).join("");
  }

  function renderCollaboration() {
    renderStats();
    renderTasks();
    renderMessages();
  }

  async function loadCollaboration(missionKey, silent = false) {
    if (!missionKey) return;
    if (!silent) document.querySelector("#collaborationState").textContent = "Loading";
    try {
      const data = await api(`/api/missions/${encodeURIComponent(missionKey)}/collaboration`);
      phase4.missionKey = missionKey;
      phase4.tasks = data.tasks || [];
      phase4.messages = data.messages || [];
      phase4.stats = data.stats || {};
      renderCollaboration();
      document.querySelector("#collaborationState").textContent = "Live";
    } catch (error) {
      if (!silent) document.querySelector("#collaborationState").textContent = error.message;
    }
  }

  async function refreshWorker() {
    try {
      const worker = await api("/api/collaboration/worker");
      document.querySelector("#collaborationWorkerState").textContent = `${worker.status} · ${worker.interval_seconds}s · dispatch ${worker.last_dispatched} · update ${worker.last_updated} · follow-up ${worker.last_followed_up}`;
    } catch (error) {
      document.querySelector("#collaborationWorkerState").textContent = error.message;
    }
  }

  function openHandoffDialog() {
    if (!state.selectedMission) return;
    const select = document.querySelector("#handoffRuntime");
    select.innerHTML = state.runtimes.map((runtime) => `<option value="${escapeHtml(runtime.key)}" ${runtime.configured ? "" : "disabled"}>${escapeHtml(runtime.name)}${runtime.configured ? "" : " · not configured"}</option>`).join("");
    const firstConfigured = state.runtimes.find((runtime) => runtime.configured);
    if (firstConfigured) select.value = firstConfigured.key;
    document.querySelector("#handoffTarget").value = firstConfigured ? `runtime:${firstConfigured.key}` : "";
    document.querySelector("#handoffMessage").textContent = `Mission ${state.selectedMission.key}`;
    document.querySelector("#handoffDialog").showModal();
  }

  async function createHandoff(event) {
    event.preventDefault();
    const mission = state.selectedMission;
    if (!mission) return;
    const message = document.querySelector("#handoffMessage");
    message.textContent = "Creating handoff…";
    const runtimeKey = document.querySelector("#handoffRuntime").value;
    const payload = {
      title: document.querySelector("#handoffTitle").value.trim(),
      objective: document.querySelector("#handoffObjective").value.trim(),
      source_identity: `agent:${mission.commander}`,
      target_runtime_key: runtimeKey,
      target_identity: document.querySelector("#handoffTarget").value.trim() || `runtime:${runtimeKey}`,
      priority: document.querySelector("#handoffPriority").value,
      review_policy: document.querySelector("#handoffReview").value,
      auto_dispatch: document.querySelector("#handoffAuto").checked,
      depends_on: document.querySelector("#handoffDepends").value.split(",").map((item) => item.trim()).filter(Boolean),
      expected_outputs: lines(document.querySelector("#handoffOutputs").value),
      acceptance_criteria: lines(document.querySelector("#handoffCriteria").value),
      context: { created_from: "command-center" },
    };
    try {
      const task = await operatorApi(`/api/missions/${encodeURIComponent(mission.key)}/handoffs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      message.textContent = `${task.key} created · ${task.status}`;
      document.querySelector("#handoffForm").reset();
      setTimeout(() => document.querySelector("#handoffDialog").close(), 650);
      await loadCollaboration(mission.key);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  async function taskAction(taskKey, action) {
    let note = "";
    if (action === "block") note = window.prompt("Why is this task blocked?") || "Blocked by operator";
    if (action === "retry") note = window.prompt("Retry instruction", "Retry with the existing work contract") || "Retry";
    try {
      await operatorApi(`/api/collaboration/tasks/${encodeURIComponent(taskKey)}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, note, result: {} }),
      });
      await loadCollaboration(phase4.missionKey);
    } catch (error) {
      document.querySelector("#collaborationState").textContent = error.message;
    }
  }

  async function reviewTask(taskKey, decision) {
    const note = window.prompt(`Review decision: ${decision}`, decision === "revise" ? "Please revise the result and attach stronger evidence." : "") || decision;
    try {
      await operatorApi(`/api/collaboration/tasks/${encodeURIComponent(taskKey)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note }),
      });
      await loadCollaboration(phase4.missionKey);
    } catch (error) {
      document.querySelector("#collaborationState").textContent = error.message;
    }
  }

  async function runTick() {
    try {
      const result = await operatorApi("/api/collaboration/tick", { method: "POST" });
      document.querySelector("#collaborationState").textContent = `Tick · dispatch ${result.dispatched} · update ${result.updated} · follow-up ${result.followed_up}`;
      await loadCollaboration(phase4.missionKey, true);
      await refreshWorker();
    } catch (error) {
      document.querySelector("#collaborationState").textContent = error.message;
    }
  }

  function extendMissionSelection() {
    const previousSelectMission = selectMission;
    selectMission = async function selectMissionWithCollaboration(key) {
      await previousSelectMission(key);
      await loadCollaboration(key);
    };
  }

  async function initialize() {
    if (phase4.initialized) return;
    phase4.initialized = true;
    installUi();
    extendMissionSelection();
    await refreshWorker();
    setInterval(refreshWorker, 10000);
    phase4.timer = setInterval(() => {
      if (!document.hidden && phase4.missionKey) void loadCollaboration(phase4.missionKey, true);
    }, 4000);

    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (state.selectedMission?.key) {
        await loadCollaboration(state.selectedMission.key);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  window.addEventListener("beforeunload", () => {
    if (phase4.timer) clearInterval(phase4.timer);
  });
  void initialize();
})();
