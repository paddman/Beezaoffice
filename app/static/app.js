const state = {
  missions: [],
  agents: [],
  runtimes: [],
  dispatches: [],
  selectedMission: null,
  syncTimer: null,
  syncBusy: false,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[char]));
const safeClass = (value = "") => String(value).toLowerCase().replace(/[^a-z0-9_-]/g, "");

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string"
      ? body.detail
      : body.detail
        ? JSON.stringify(body.detail)
        : `Request failed (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function operatorApi(path, options = {}, promptForToken = true) {
  let token = localStorage.getItem("beezaToken") || "";

  async function call(currentToken) {
    return api(path, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {}),
      },
    });
  }

  try {
    return await call(token);
  } catch (error) {
    if (error.status !== 401 || !promptForToken) throw error;
    token = window.prompt("Enter the BeezaOffice operator token") || "";
    if (!token) throw error;
    const result = await call(token);
    localStorage.setItem("beezaToken", token);
    return result;
  }
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function renderStats(health) {
  const active = state.agents.filter((agent) => agent.status === "RUNNING").length;
  const waiting = state.agents.filter((agent) => agent.status === "WAITING").length;
  const approvals = state.missions.filter((mission) => mission.status.includes("APPROVAL")).length;
  const cards = [
    ["Registered agents", health.registered_agents, "Target: 1,000"],
    ["Active agents", active, "Runtime instances"],
    ["Waiting agents", waiting, "Dependencies tracked"],
    ["Open missions", state.missions.length, "Across all departments"],
    ["Pending approvals", Math.max(approvals, 1), "Human control required"],
    ["Agent runtimes", `${health.runtime_online}/${health.runtime_connectors}`, `${health.runtime_configured} configured`],
  ];
  $("#stats").innerHTML = cards.map(([label, value, detail]) => `
    <article class="stat-card"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>
  `).join("");
}

function renderMissions() {
  $("#missionCount").textContent = state.missions.length;
  const mapMissionCount = $("#mapMissionCount");
  if (mapMissionCount) mapMissionCount.textContent = state.missions.length;

  $("#missionList").innerHTML = state.missions.map((mission) => `
    <button class="mission-card ${state.selectedMission?.key === mission.key ? "active" : ""}" data-mission="${escapeHtml(mission.key)}">
      <header><strong>${escapeHtml(mission.title)}</strong><span class="priority ${mission.priority}">${mission.priority}</span></header>
      <p>${escapeHtml(mission.waiting_for || mission.objective)}</p>
      <div class="progress"><i style="width:${Number(mission.progress)}%"></i></div>
      <footer><span>${escapeHtml(mission.status)}</span><span>${mission.progress}% · ${escapeHtml(mission.commander)}</span></footer>
    </button>
  `).join("");

  document.querySelectorAll("[data-mission]").forEach((button) => {
    button.addEventListener("click", () => selectMission(button.dataset.mission));
  });
}

function renderAgents() {
  $("#agentCount").textContent = state.agents.length;
  $("#agentGrid").innerHTML = state.agents.map((agent) => {
    const avatarClass = `avatar-${safeClass(agent.key)}`;
    return `
      <article class="agent-card" data-agent="${escapeHtml(agent.key)}">
        <header>
          <div class="avatar ${avatarClass}" role="img" aria-label="Portrait of ${escapeHtml(agent.name)}"></div>
          <div><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></div>
        </header>
        <div class="agent-status"><span>${escapeHtml(agent.department)}</span><b class="${agent.status}">${escapeHtml(agent.status)}</b></div>
      </article>
    `;
  }).join("");
}

function runtimeMark(runtime) {
  const marks = { openclaw: "OC", cherryagent: "CH", hermes: "HE", thclaws: "TH" };
  return marks[runtime.key] || runtime.name.slice(0, 2).toUpperCase();
}

function runtimeName(runtimeKey) {
  return state.runtimes.find((runtime) => runtime.key === runtimeKey)?.name || runtimeKey;
}

function renderRuntimes() {
  $("#runtimeCount").textContent = state.runtimes.length;
  const online = state.runtimes.filter((runtime) => runtime.status === "ONLINE").length;
  $("#runtimeOnline").textContent = `${online} online`;

  $("#runtimeGrid").innerHTML = state.runtimes.map((runtime) => {
    const statusClass = safeClass(runtime.status);
    const endpoint = runtime.configured ? runtime.base_url : "Set base URL in .env";
    const target = runtime.agent_target || runtime.model || "Platform default";
    const capabilities = (runtime.capabilities || []).slice(0, 4).map((capability) => (
      `<span>${escapeHtml(capability)}</span>`
    )).join("");
    return `
      <article class="runtime-card ${statusClass}" data-runtime-card="${escapeHtml(runtime.key)}">
        <header>
          <div class="runtime-mark ${safeClass(runtime.key)}">${escapeHtml(runtimeMark(runtime))}</div>
          <div class="runtime-title">
            <strong>${escapeHtml(runtime.name)}</strong>
            <small>${escapeHtml(runtime.transport)}</small>
          </div>
          <b class="runtime-status ${statusClass}">${escapeHtml(runtime.status)}</b>
        </header>
        <dl>
          <div><dt>Endpoint</dt><dd title="${escapeHtml(endpoint)}">${escapeHtml(endpoint)}</dd></div>
          <div><dt>Target</dt><dd>${escapeHtml(target)}</dd></div>
          <div><dt>Auth</dt><dd>${runtime.auth_configured ? "Bearer configured" : runtime.configured ? "No token set" : "Not configured"}</dd></div>
        </dl>
        <div class="runtime-capabilities">${capabilities}</div>
        <div class="runtime-actions">
          <button class="secondary runtime-probe" data-runtime-probe="${escapeHtml(runtime.key)}">Probe</button>
          <button class="primary runtime-dispatch" data-runtime-dispatch="${escapeHtml(runtime.key)}" ${runtime.configured && state.selectedMission ? "" : "disabled"}>Dispatch mission</button>
        </div>
        ${runtime.last_error ? `<p class="runtime-error">${escapeHtml(runtime.last_error)}</p>` : ""}
      </article>
    `;
  }).join("");

  document.querySelectorAll("[data-runtime-probe]").forEach((button) => {
    button.addEventListener("click", () => probeRuntime(button.dataset.runtimeProbe));
  });
  document.querySelectorAll("[data-runtime-dispatch]").forEach((button) => {
    button.addEventListener("click", () => dispatchRuntime(button.dataset.runtimeDispatch));
  });
}

function renderDispatches() {
  const container = $("#dispatchList");
  const count = $("#dispatchCount");
  if (count) count.textContent = String(state.dispatches.length);
  if (!container) return;

  if (!state.dispatches.length) {
    container.innerHTML = `<p class="dispatch-empty">No external runtime work has been dispatched for this mission.</p>`;
    return;
  }

  container.innerHTML = state.dispatches.map((dispatch) => {
    const statusClass = safeClass(dispatch.status);
    const summary = dispatch.output?.summary || dispatch.error || "Waiting for runtime output.";
    const remote = dispatch.remote_id || "synchronous";
    const latency = dispatch.output?.latency_ms;
    return `
      <article class="dispatch-card ${statusClass}" data-dispatch-card="${escapeHtml(dispatch.key)}">
        <header>
          <div>
            <strong>${escapeHtml(runtimeName(dispatch.runtime_key))}</strong>
            <small>${escapeHtml(dispatch.key)} · Remote ${escapeHtml(remote)}</small>
          </div>
          <span class="dispatch-status ${statusClass}">${escapeHtml(dispatch.status)}</span>
        </header>
        <p>${escapeHtml(summary)}</p>
        <footer>
          <span>Updated ${escapeHtml(formatDateTime(dispatch.updated_at))}${latency ? ` · ${escapeHtml(latency)} ms` : ""}</span>
          <div class="dispatch-actions">
            ${dispatch.can_sync ? `<button class="secondary" data-dispatch-sync="${escapeHtml(dispatch.key)}">Sync</button>` : ""}
            ${dispatch.can_approve ? `<button class="primary" data-dispatch-approve="${escapeHtml(dispatch.key)}">Approve once</button><button class="danger-button" data-dispatch-deny="${escapeHtml(dispatch.key)}">Deny</button>` : ""}
            ${dispatch.can_stop ? `<button class="danger-button" data-dispatch-stop="${escapeHtml(dispatch.key)}">Stop</button>` : ""}
          </div>
        </footer>
      </article>
    `;
  }).join("");

  document.querySelectorAll("[data-dispatch-sync]").forEach((button) => {
    button.addEventListener("click", () => syncDispatch(button.dataset.dispatchSync));
  });
  document.querySelectorAll("[data-dispatch-stop]").forEach((button) => {
    button.addEventListener("click", () => stopDispatch(button.dataset.dispatchStop));
  });
  document.querySelectorAll("[data-dispatch-approve]").forEach((button) => {
    button.addEventListener("click", () => resolveDispatchApproval(button.dataset.dispatchApprove, "once"));
  });
  document.querySelectorAll("[data-dispatch-deny]").forEach((button) => {
    button.addEventListener("click", () => resolveDispatchApproval(button.dataset.dispatchDeny, "deny"));
  });
}

function renderMissionDetail(mission) {
  state.selectedMission = mission;
  state.dispatches = mission.dispatches || [];
  $("#roomTitle").textContent = `${mission.key} · ${mission.title}`;
  $("#roomStatus").textContent = mission.status;
  $("#roomObjective").textContent = mission.objective;
  $("#roomCommander").textContent = mission.commander;
  $("#roomProgress").textContent = `${mission.progress}%`;
  $("#roomWaiting").textContent = mission.waiting_for || "No dependency";
  $("#timeline").innerHTML = mission.events.length ? mission.events.map((event) => `
    <article class="timeline-item">
      <header><strong>${escapeHtml(event.actor)}</strong><span>${escapeHtml(event.type)}</span></header>
      <p>${escapeHtml(event.message)}</p>
    </article>
  `).join("") : `<p class="objective">No collaboration events yet.</p>`;
  renderDispatches();
  renderMissions();
  renderRuntimes();
}

async function selectMission(key) {
  document.querySelectorAll("[data-mission]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mission === key);
  });
  const mission = await api(`/api/missions/${encodeURIComponent(key)}`);
  renderMissionDetail(mission);
}

async function refreshSelectedMission() {
  if (!state.selectedMission) return;
  const mission = await api(`/api/missions/${encodeURIComponent(state.selectedMission.key)}`);
  state.missions = await api("/api/missions");
  renderMissionDetail(mission);
}

async function probeRuntime(runtimeKey) {
  const runtime = state.runtimes.find((item) => item.key === runtimeKey);
  const message = $("#runtimeMessage");
  message.textContent = `Probing ${runtime?.name || runtimeKey}…`;
  try {
    const result = await operatorApi(`/api/runtimes/${encodeURIComponent(runtimeKey)}/probe`, { method: "POST" });
    state.runtimes = state.runtimes.map((item) => item.key === runtimeKey ? result : item);
    renderRuntimes();
    message.textContent = result.status === "ONLINE"
      ? `${result.name} is online${result.last_latency_ms ? ` · ${result.last_latency_ms} ms` : ""}.`
      : `${result.name}: ${result.status}${result.last_error ? ` · ${result.last_error}` : ""}`;
  } catch (error) {
    message.textContent = error.message;
  }
}

async function dispatchRuntime(runtimeKey) {
  const runtime = state.runtimes.find((item) => item.key === runtimeKey);
  const mission = state.selectedMission;
  const message = $("#runtimeMessage");
  if (!mission) {
    message.textContent = "Select a mission before dispatching work.";
    return;
  }

  message.textContent = `Dispatching ${mission.key} to ${runtime?.name || runtimeKey}…`;
  document.querySelectorAll(".runtime-dispatch").forEach((button) => { button.disabled = true; });
  try {
    const result = await operatorApi(`/api/runtimes/${encodeURIComponent(runtimeKey)}/dispatch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mission_key: mission.key,
        roles: [mission.commander],
        tags: [mission.priority.toLowerCase(), "command-center"],
      }),
    });
    message.textContent = `${runtime?.name || runtimeKey} accepted ${mission.key}. Dispatch ${result.key} · ${result.status}.`;
    state.runtimes = await api("/api/runtimes");
    await refreshSelectedMission();
  } catch (error) {
    message.textContent = error.message;
    state.runtimes = await api("/api/runtimes").catch(() => state.runtimes);
    renderRuntimes();
  }
}

async function syncDispatch(dispatchKey, silent = false) {
  if (silent && !localStorage.getItem("beezaToken")) return;
  const message = $("#runtimeMessage");
  if (!silent) message.textContent = `Syncing ${dispatchKey}…`;
  try {
    const result = await operatorApi(
      `/api/runtime-dispatches/${encodeURIComponent(dispatchKey)}/sync`,
      { method: "POST" },
      !silent,
    );
    state.dispatches = state.dispatches.map((item) => item.key === dispatchKey ? result : item);
    renderDispatches();
    if (!silent) message.textContent = `${dispatchKey} is ${result.status}.`;
    return result;
  } catch (error) {
    if (!silent) message.textContent = error.message;
    return null;
  }
}

async function stopDispatch(dispatchKey) {
  if (!window.confirm(`Stop ${dispatchKey} at the next safe interruption point?`)) return;
  const message = $("#runtimeMessage");
  message.textContent = `Requesting safe stop for ${dispatchKey}…`;
  try {
    const result = await operatorApi(`/api/runtime-dispatches/${encodeURIComponent(dispatchKey)}/stop`, { method: "POST" });
    message.textContent = `${dispatchKey}: ${result.status}.`;
    await refreshSelectedMission();
  } catch (error) {
    message.textContent = error.message;
  }
}

async function resolveDispatchApproval(dispatchKey, choice) {
  const action = choice === "deny" ? "deny" : "approve once";
  if (!window.confirm(`${action} for ${dispatchKey}?`)) return;
  const message = $("#runtimeMessage");
  message.textContent = `Resolving approval for ${dispatchKey}…`;
  try {
    const result = await operatorApi(`/api/runtime-dispatches/${encodeURIComponent(dispatchKey)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice }),
    });
    message.textContent = `${dispatchKey}: approval ${choice} recorded · ${result.status}.`;
    await refreshSelectedMission();
  } catch (error) {
    message.textContent = error.message;
  }
}

async function autoSyncActiveDispatches() {
  if (state.syncBusy || document.hidden || !state.selectedMission) return;
  const active = state.dispatches.filter((dispatch) => (
    dispatch.can_sync && ["DISPATCHING", "STARTED", "RUNNING", "QUEUED", "WAITING_APPROVAL", "STOPPING"].includes(dispatch.status)
  ));
  if (!active.length || !localStorage.getItem("beezaToken")) return;
  state.syncBusy = true;
  try {
    await Promise.all(active.map((dispatch) => syncDispatch(dispatch.key, true)));
    await refreshSelectedMission();
  } finally {
    state.syncBusy = false;
  }
}

function startRuntimeSync() {
  if (state.syncTimer) clearInterval(state.syncTimer);
  state.syncTimer = setInterval(autoSyncActiveDispatches, 5000);
}

async function loadDashboard() {
  try {
    const [health, agents, missions, runtimes] = await Promise.all([
      api("/api/health"),
      api("/api/agents"),
      api("/api/missions"),
      api("/api/runtimes"),
    ]);
    state.agents = agents;
    state.missions = missions;
    state.runtimes = runtimes;
    renderStats(health);
    renderAgents();
    renderMissions();
    renderRuntimes();
    if (missions[0]) await selectMission(missions[0].key);
    startRuntimeSync();
  } catch (error) {
    document.body.innerHTML = `<main style="padding:40px"><h1>BeezaOffice is unavailable</h1><p>${escapeHtml(error.message)}</p></main>`;
  }
}

const dialog = $("#missionDialog");
$("#newMission").addEventListener("click", () => dialog.showModal());

function openOrganizationMap() {
  $("#organizationMap")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function openRuntimeMesh() {
  $("#runtimeMesh")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#organizationMapButton")?.addEventListener("click", openOrganizationMap);
$("#organizationNav")?.addEventListener("click", openOrganizationMap);
$("#runtimeNav")?.addEventListener("click", openRuntimeMesh);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void autoSyncActiveDispatches();
});

$("#missionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    title: $("#missionTitle").value.trim(),
    objective: $("#missionObjective").value.trim(),
    priority: $("#missionPriority").value,
  };
  const message = $("#formMessage");
  message.textContent = "Creating mission…";
  try {
    const result = await operatorApi("/api/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    message.textContent = `${result.key} created. Beeza Commander is planning the team.`;
    $("#missionForm").reset();
    setTimeout(async () => {
      dialog.close();
      state.missions = await api("/api/missions");
      renderMissions();
      await selectMission(result.key);
    }, 900);
  } catch (error) {
    message.textContent = error.message;
  }
});

loadDashboard();
