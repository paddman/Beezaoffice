const state = {
  missions: [],
  agents: [],
  runtimes: [],
  selectedMission: null,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[char]));
const safeClass = (value = "") => String(value).toLowerCase().replace(/[^a-z0-9_-]/g, "");

async function api(path, options = {}) {
  const response = await fetch(path, options);
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

async function operatorApi(path, options = {}) {
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
    if (error.status !== 401) throw error;
    token = window.prompt("Enter the BeezaOffice operator token") || "";
    if (!token) throw error;
    const result = await call(token);
    localStorage.setItem("beezaToken", token);
    return result;
  }
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
  const marks = {
    openclaw: "OC",
    cherryagent: "CH",
    hermes: "HE",
    thclaws: "TH",
  };
  return marks[runtime.key] || runtime.name.slice(0, 2).toUpperCase();
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
          <button class="primary runtime-dispatch" data-runtime-dispatch="${escapeHtml(runtime.key)}" ${runtime.configured && state.selectedMission ? "" : "disabled"}>
            Dispatch mission
          </button>
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

async function selectMission(key) {
  document.querySelectorAll("[data-mission]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mission === key);
  });
  const mission = await api(`/api/missions/${encodeURIComponent(key)}`);
  state.selectedMission = mission;
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
  renderMissions();
  renderRuntimes();
}

async function probeRuntime(runtimeKey) {
  const runtime = state.runtimes.find((item) => item.key === runtimeKey);
  const message = $("#runtimeMessage");
  message.textContent = `Probing ${runtime?.name || runtimeKey}…`;
  try {
    const result = await operatorApi(`/api/runtimes/${encodeURIComponent(runtimeKey)}/probe`, {
      method: "POST",
    });
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
  document.querySelectorAll(".runtime-dispatch").forEach((button) => {
    button.disabled = true;
  });

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
    state.missions = await api("/api/missions");
    state.runtimes = await api("/api/runtimes");
    await selectMission(mission.key);
  } catch (error) {
    message.textContent = error.message;
    state.runtimes = await api("/api/runtimes").catch(() => state.runtimes);
    renderRuntimes();
  }
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
