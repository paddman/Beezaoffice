(() => {
  const phase11 = {
    status: null,
    tasks: [],
    events: [],
    selected: null,
    initialized: false,
    timer: null,
  };

  function installUi() {
    if (document.querySelector("#protocolGateway")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "protocolNav";
    nav.innerHTML = 'Protocol Gateway <span id="protocolNavCount">0</span>';
    document.querySelector("#sopNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel protocol-panel";
    panel.id = "protocolGateway";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 11 · PROTOCOL GATEWAY</p><h2>Agent Interoperability Gateway</h2></div>
        <div class="protocol-header-state"><span id="protocolState">Starting</span><b id="protocolCount">0</b></div>
      </div>
      <p class="dispatch-intro">Expose BeezaOffice as a governed A2A agent, stateless MCP server, OpenAI-compatible ingress, signed webhook target and durable SSE event source. All execution still passes through identity, policy, scheduler, runtime and evidence controls.</p>
      <div class="protocol-toolbar">
        <span id="protocolWorkerSummary">Loading protocol worker…</span>
        <div class="protocol-toolbar-actions"><button class="secondary" id="protocolTick">Run sync</button><button class="secondary" id="protocolRefresh">Refresh</button><button class="primary" id="protocolTest">Send A2A test</button></div>
      </div>
      <div id="protocolStats" class="protocol-stats"></div>
      <div id="protocolInterfaces" class="protocol-interface-grid"></div>
      <div class="protocol-layout">
        <section class="protocol-box">
          <div class="protocol-box-head"><div><strong>Gateway tasks</strong><small>A2A, MCP, OpenAI-compatible and webhook ingress</small></div><span id="protocolTaskCount" class="protocol-state">0 tasks</span></div>
          <div id="protocolTaskList" class="protocol-task-list"></div>
        </section>
        <section class="protocol-box">
          <div class="protocol-box-head"><div><strong>Protocol task detail</strong><small>Mission mapping, artifacts and durable updates</small></div><div id="protocolDetailActions" class="protocol-actions"></div></div>
          <div id="protocolDetail" class="protocol-detail"><p class="protocol-empty">Select a gateway task.</p></div>
        </section>
      </div>
      <p id="protocolMessage" class="protocol-message"></p>
    `;
    document.querySelector("#sopBuilder")?.after(panel);

    const dialog = document.createElement("dialog");
    dialog.id = "protocolTestDialog";
    dialog.innerHTML = `
      <form method="dialog" id="protocolTestForm">
        <div class="dialog-head"><div><p class="eyebrow">A2A 1.0 TEST</p><h2>Send Governed Message</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="protocol-form-grid">
          <label>Title<input id="protocolTestTitle" value="Protocol gateway verification" required /></label>
          <label>Priority<select id="protocolTestPriority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select></label>
          <label>Preferred runtime<select id="protocolTestRuntime"><option value="">Intelligent routing</option></select></label>
          <label>Required clearance<select id="protocolTestClearance"><option>PUBLIC</option><option selected>INTERNAL</option><option>CONFIDENTIAL</option><option>RESTRICTED</option></select></label>
          <label class="full">Required skills<input id="protocolTestSkills" placeholder="evidence, metrics" /></label>
          <label class="full">Message<textarea id="protocolTestMessage" required minlength="10">Inspect the current BeezaOffice gateway configuration, identify any missing runtime prerequisites, and return a concise evidence-backed readiness report.</textarea></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Send message</button></div>
        <p id="protocolTestFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(dialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#protocolTick").addEventListener("click", runTick);
    panel.querySelector("#protocolRefresh").addEventListener("click", () => loadGateway());
    panel.querySelector("#protocolTest").addEventListener("click", openTestDialog);
    dialog.querySelector("#protocolTestForm").addEventListener("submit", sendTest);
  }

  function showMessage(message, type = "") {
    const node = document.querySelector("#protocolMessage");
    if (!node) return;
    node.textContent = message;
    node.className = `protocol-message ${type}`;
  }

  function interfaces() {
    const urls = phase11.status?.interfaces || {};
    return [
      ["A2A", "A2A 1.0", "Agent card, send, poll, cancel and SSE subscribe", urls.a2a || "/message:send", "a2a"],
      ["MCP", "MCP", "Stateless JSON-RPC tools for agents, tasks and SOP runs", urls.mcp || "/mcp", "mcp"],
      ["OAI", "OpenAI ingress", "Synchronous wait with governed async task fallback", urls.openai || "/v1/chat/completions", "openai"],
      ["HOOK", "Webhook", "Bearer or HMAC authenticated task and SOP trigger", urls.webhook || "/hooks/{channel}", "webhook"],
      ["SSE", "Event stream", "Durable gateway event feed for external observers", urls.events || "/api/protocol/events/stream", "sse"],
    ];
  }

  function renderInterfaces() {
    const publicUrl = String(phase11.status?.public_url || window.location.origin).replace(/\/$/, "");
    document.querySelector("#protocolInterfaces").innerHTML = interfaces().map(([mark, name, description, path, cls]) => {
      const endpoint = path.startsWith("http") ? path : `${publicUrl}${path}`;
      return `<article class="protocol-interface"><header><div><strong>${escapeHtml(name)}</strong><small>${escapeHtml(description)}</small></div><span class="protocol-mark ${cls}">${mark}</span></header><code title="${escapeHtml(endpoint)}">${escapeHtml(endpoint)}</code><footer><button class="secondary" data-protocol-copy="${escapeHtml(endpoint)}">Copy</button></footer></article>`;
    }).join("");
    document.querySelectorAll("[data-protocol-copy]").forEach((button) => button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.protocolCopy);
        showMessage("Endpoint copied.", "success");
      } catch {
        showMessage(button.dataset.protocolCopy);
      }
    }));
  }

  function renderStats() {
    const stats = phase11.status?.stats || {};
    const cards = [
      ["Gateway tasks", stats.tasks || 0, `${stats.active_tasks || 0} active`],
      ["Completed", stats.completed_tasks || 0, "Evidence artifacts returned"],
      ["Failed", stats.failed_tasks || 0, "Governed failure records"],
      ["Events", stats.events || 0, "Durable status updates"],
      ["A2A", stats.protocols?.a2a || 0, `Protocol ${phase11.status?.a2a_version || "1.0"}`],
      ["MCP", stats.protocols?.mcp || 0, phase11.status?.mcp_protocol_version || "2025-06-18"],
    ];
    document.querySelector("#protocolStats").innerHTML = cards.map(([label, value, detail]) => `<article class="protocol-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
    document.querySelector("#protocolCount").textContent = String(stats.tasks || 0);
    document.querySelector("#protocolNavCount").textContent = String(stats.active_tasks || 0);
    const worker = phase11.status?.worker || {};
    document.querySelector("#protocolState").textContent = worker.status || "starting";
    document.querySelector("#protocolWorkerSummary").textContent = `${worker.status || "starting"} · ${worker.interval_seconds || 2}s · processed ${worker.last_processed || 0} · changed ${worker.last_changed || 0} · completed ${worker.last_completed || 0} · failed ${worker.last_failed || 0}${worker.last_error ? ` · ${worker.last_error}` : ""}`;
  }

  function renderTasks() {
    const container = document.querySelector("#protocolTaskList");
    document.querySelector("#protocolTaskCount").textContent = `${phase11.tasks.length} tasks`;
    if (!phase11.tasks.length) {
      container.innerHTML = '<p class="protocol-empty">No gateway tasks yet.</p>';
      return;
    }
    container.innerHTML = phase11.tasks.map((task) => `
      <button class="protocol-task ${phase11.selected?.id === task.id ? "active" : ""}" data-protocol-task="${escapeHtml(task.id)}">
        <header><div><strong>${escapeHtml(task.id)}</strong><small>${escapeHtml(task.protocol.toUpperCase())} · ${escapeHtml(task.client_identity)}</small></div><span class="protocol-state ${safeClass(task.state)}">${escapeHtml(task.state.replace("TASK_STATE_", ""))}</span></header>
        <p>${escapeHtml(task.status_message || "No status message")}</p>
        <footer><span>${escapeHtml(task.mission_key || "No mission")}</span><span>${escapeHtml(formatDateTime(task.updated_at))}</span></footer>
      </button>
    `).join("");
    container.querySelectorAll("[data-protocol-task]").forEach((button) => button.addEventListener("click", () => selectTask(button.dataset.protocolTask)));
  }

  function artifactText(artifact) {
    const parts = artifact?.parts || [];
    const text = parts.find((part) => part && part.text)?.text;
    if (text) return String(text);
    const data = parts.find((part) => part && part.data)?.data;
    return data ? JSON.stringify(data, null, 2) : JSON.stringify(artifact, null, 2);
  }

  function renderDetail() {
    const container = document.querySelector("#protocolDetail");
    const actions = document.querySelector("#protocolDetailActions");
    const task = phase11.selected;
    if (!task) {
      actions.innerHTML = "";
      container.innerHTML = '<p class="protocol-empty">Select a gateway task.</p>';
      return;
    }
    const terminal = ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"].includes(task.state);
    actions.innerHTML = `<button class="secondary" id="protocolPollSelected">Poll</button>${terminal ? "" : '<button class="danger-button" id="protocolCancelSelected">Cancel</button>'}`;
    document.querySelector("#protocolPollSelected")?.addEventListener("click", () => selectTask(task.id));
    document.querySelector("#protocolCancelSelected")?.addEventListener("click", cancelSelected);
    const taskEvents = phase11.events.filter((event) => event.task_id === task.id).sort((a, b) => Number(a.sequence) - Number(b.sequence));
    const artifacts = (task.artifacts || []).map((artifact) => `<article class="protocol-artifact"><strong>${escapeHtml(artifact.name || artifact.artifactId || "Artifact")}</strong><small>${escapeHtml(artifact.description || "Evidence envelope")}</small><pre>${escapeHtml(artifactText(artifact))}</pre></article>`).join("") || '<p class="protocol-empty">No artifacts yet.</p>';
    const events = taskEvents.map((event) => `<article class="protocol-event"><strong>#${event.sequence} · ${escapeHtml(event.type)}</strong><small>${escapeHtml(formatDateTime(event.occurred_at))}</small><pre>${escapeHtml(JSON.stringify(event.payload || {}, null, 2))}</pre></article>`).join("") || '<p class="protocol-empty">No durable events yet.</p>';
    container.innerHTML = `
      <div class="protocol-detail-head"><div><h3>${escapeHtml(task.id)}</h3><p>${escapeHtml(task.status_message || "")}</p></div><span class="protocol-state ${safeClass(task.state)}">${escapeHtml(task.state)}</span></div>
      <div class="protocol-detail-meta">
        <div><span>Protocol</span><strong>${escapeHtml(task.protocol)}</strong></div>
        <div><span>Client</span><strong>${escapeHtml(task.client_identity)}</strong></div>
        <div><span>Mission</span><strong>${escapeHtml(task.mission_key || "—")}</strong></div>
        <div><span>Work package</span><strong>${escapeHtml(task.collaboration_task_key || "—")}</strong></div>
        <div><span>Context</span><strong>${escapeHtml(task.context_id || "—")}</strong></div>
        <div><span>Message</span><strong>${escapeHtml(task.message_id || "—")}</strong></div>
        <div><span>Created</span><strong>${escapeHtml(formatDateTime(task.created_at))}</strong></div>
        <div><span>Completed</span><strong>${escapeHtml(formatDateTime(task.completed_at))}</strong></div>
      </div>
      <section class="protocol-section"><h4>Artifacts</h4>${artifacts}</section>
      <section class="protocol-section"><h4>Event sequence</h4>${events}</section>
    `;
  }

  async function loadGateway(silent = false) {
    try {
      const [status, tasks, events] = await Promise.all([
        operatorApi("/api/protocol/status", {}, true),
        operatorApi("/api/protocol/tasks?limit=200", {}, true),
        operatorApi("/api/protocol/events?limit=1000", {}, true),
      ]);
      phase11.status = status;
      phase11.tasks = tasks;
      phase11.events = events;
      if (phase11.selected) phase11.selected = tasks.find((task) => task.id === phase11.selected.id) || null;
      renderStats();
      renderInterfaces();
      renderTasks();
      renderDetail();
      if (!silent) showMessage("Protocol gateway refreshed.", "success");
    } catch (error) {
      document.querySelector("#protocolState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function selectTask(taskId) {
    try {
      const task = await operatorApi(`/tasks/${encodeURIComponent(taskId)}`, { headers: { "A2A-Version": "1.0" } }, true);
      phase11.selected = {
        id: task.id,
        protocol: task.metadata?.protocol || phase11.tasks.find((item) => item.id === task.id)?.protocol || "a2a",
        client_identity: phase11.tasks.find((item) => item.id === task.id)?.client_identity || "",
        message_id: task.history?.[0]?.messageId,
        context_id: task.contextId,
        state: task.status?.state,
        mission_key: task.metadata?.missionKey,
        collaboration_task_key: task.metadata?.collaborationTaskKey,
        sop_run_key: task.metadata?.sopRunKey,
        status_message: task.status?.message?.parts?.[0]?.text,
        artifacts: task.artifacts || [],
        created_at: phase11.tasks.find((item) => item.id === task.id)?.created_at,
        updated_at: task.status?.timestamp,
        completed_at: phase11.tasks.find((item) => item.id === task.id)?.completed_at,
      };
      await loadGateway(true);
      phase11.selected = phase11.tasks.find((item) => item.id === taskId) || phase11.selected;
      renderTasks();
      renderDetail();
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function openTestDialog() {
    const runtime = document.querySelector("#protocolTestRuntime");
    runtime.innerHTML = '<option value="">Intelligent routing</option>' + state.runtimes.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.name)}</option>`).join("");
    document.querySelector("#protocolTestFormMessage").textContent = "The message is submitted through the public A2A endpoint with Beeza Governance headers.";
    document.querySelector("#protocolTestDialog").showModal();
  }

  async function sendTest(event) {
    event.preventDefault();
    const message = document.querySelector("#protocolTestFormMessage");
    message.textContent = "Submitting A2A message…";
    const preferredRuntime = document.querySelector("#protocolTestRuntime").value;
    const skills = document.querySelector("#protocolTestSkills").value.split(",").map((item) => item.trim()).filter(Boolean);
    try {
      const response = await operatorApi("/message:send", {
        method: "POST",
        headers: { "Content-Type": "application/json", "A2A-Version": "1.0" },
        body: JSON.stringify({
          message: {
            messageId: `ui-${Date.now()}`,
            role: "ROLE_USER",
            parts: [{ text: document.querySelector("#protocolTestMessage").value.trim() }],
            metadata: {
              title: document.querySelector("#protocolTestTitle").value.trim(),
              priority: document.querySelector("#protocolTestPriority").value,
              requiredSkills: skills,
              requiredClearance: document.querySelector("#protocolTestClearance").value,
              preferredRuntimeKey: preferredRuntime || null,
            },
          },
          configuration: { returnImmediately: true, acceptedOutputModes: ["text/plain", "application/json"] },
        }),
      }, true);
      message.textContent = `Accepted ${response.task.id}.`;
      setTimeout(() => document.querySelector("#protocolTestDialog").close(), 650);
      await loadGateway(true);
      await selectTask(response.task.id);
      showMessage(`A2A task ${response.task.id} submitted.`, "success");
    } catch (error) {
      message.textContent = error.message;
    }
  }

  async function cancelSelected() {
    const task = phase11.selected;
    if (!task || !window.confirm(`Cancel gateway task ${task.id}? This does not force-stop remote work already accepted by a runtime.`)) return;
    try {
      await operatorApi(`/tasks/${encodeURIComponent(task.id)}:cancel`, {
        method: "POST",
        headers: { "A2A-Version": "1.0" },
      }, true);
      showMessage(`${task.id} canceled at the gateway.`, "success");
      await loadGateway(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function runTick() {
    try {
      const result = await operatorApi("/api/protocol/tick", { method: "POST" }, true);
      showMessage(`Protocol sync processed ${result.processed}, changed ${result.changed}, completed ${result.completed}, failed ${result.failed}.`, "success");
      await loadGateway(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function startPolling() {
    if (phase11.timer) clearInterval(phase11.timer);
    phase11.timer = setInterval(() => {
      if (!document.hidden) void loadGateway(true);
    }, 10000);
  }

  async function initialize() {
    if (phase11.initialized) return;
    phase11.initialized = true;
    installUi();
    startPolling();
    await loadGateway(true);
  }

  void initialize();
})();
