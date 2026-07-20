const state = { missions: [], agents: [], selectedMission: null };

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[char]));

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
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
  ];
  $("#stats").innerHTML = cards.map(([label, value, detail]) => `
    <article class="stat-card"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>
  `).join("");
}

function renderMissions() {
  $("#missionCount").textContent = state.missions.length;
  $("#missionList").innerHTML = state.missions.map((mission, index) => `
    <button class="mission-card ${index === 0 ? "active" : ""}" data-mission="${escapeHtml(mission.key)}">
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
  $("#agentGrid").innerHTML = state.agents.map((agent) => `
    <article class="agent-card">
      <header>
        <div class="avatar">${escapeHtml(agent.name.slice(0, 1))}</div>
        <div><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.role)}</small></div>
      </header>
      <div class="agent-status"><span>${escapeHtml(agent.department)}</span><b class="${agent.status}">${escapeHtml(agent.status)}</b></div>
    </article>
  `).join("");
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
}

async function loadDashboard() {
  try {
    const [health, agents, missions] = await Promise.all([
      api("/api/health"),
      api("/api/agents"),
      api("/api/missions"),
    ]);
    state.agents = agents;
    state.missions = missions;
    renderStats(health);
    renderAgents();
    renderMissions();
    if (missions[0]) await selectMission(missions[0].key);
  } catch (error) {
    document.body.innerHTML = `<main style="padding:40px"><h1>BeezaOffice is unavailable</h1><p>${escapeHtml(error.message)}</p></main>`;
  }
}

const dialog = $("#missionDialog");
$("#newMission").addEventListener("click", () => dialog.showModal());

$("#missionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    title: $("#missionTitle").value.trim(),
    objective: $("#missionObjective").value.trim(),
    priority: $("#missionPriority").value,
  };
  const message = $("#formMessage");
  message.textContent = "Creating mission…";

  async function createWithToken(token) {
    return api("/api/missions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });
  }

  try {
    let token = localStorage.getItem("beezaToken") || "";
    let result;
    try {
      result = await createWithToken(token);
    } catch (error) {
      if (error.status !== 401) throw error;
      token = window.prompt("Enter the BeezaOffice operator token") || "";
      if (!token) throw error;
      result = await createWithToken(token);
      localStorage.setItem("beezaToken", token);
    }
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
