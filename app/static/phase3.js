(() => {
  const phase3 = {
    events: [],
    source: null,
    missionKey: null,
    filter: "ALL",
    initialized: false,
  };

  function installUi() {
    if (document.querySelector("#runtimeEventStream")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "runtimeEventsNav";
    nav.innerHTML = 'Live Events <span id="runtimeEventNavCount">0</span>';
    document.querySelector("#runtimeNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel runtime-events-panel";
    panel.id = "runtimeEventStream";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 3 · UNIFIED EVENT STREAM</p><h2>Live Runtime Events</h2></div>
        <div class="event-stream-state"><span id="eventStreamState" class="stream-status disconnected">Disconnected</span><b id="runtimeEventCount">0</b></div>
      </div>
      <p class="dispatch-intro">CherryAgent and Hermes activity is normalized into one durable mission feed for task progress, handoffs, evidence, approvals, results and failures.</p>
      <div class="event-worker-state"><span>Server event worker</span><strong id="eventWorkerState">Starting</strong></div>
      <div class="event-filter-bar">
        <button class="event-filter active" data-event-filter="ALL">All</button>
        <button class="event-filter" data-event-filter="TASK">Tasks</button>
        <button class="event-filter" data-event-filter="HANDOFF">Handoffs</button>
        <button class="event-filter" data-event-filter="EVIDENCE">Evidence</button>
        <button class="event-filter" data-event-filter="APPROVAL">Approvals</button>
        <button class="event-filter" data-event-filter="ERROR">Errors</button>
      </div>
      <div id="runtimeEventList" class="runtime-event-list"></div>
    `;
    document.querySelector("#missionRuntimeActivity")?.after(panel);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelectorAll("[data-event-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        phase3.filter = button.dataset.eventFilter || "ALL";
        panel.querySelectorAll("[data-event-filter]").forEach((item) => item.classList.toggle("active", item === button));
        renderEvents();
      });
    });
  }

  function matchesFilter(event) {
    if (phase3.filter === "ALL") return true;
    const type = String(event.type || "").toUpperCase();
    const severity = String(event.severity || "").toUpperCase();
    if (phase3.filter === "ERROR") {
      return severity === "ERROR" || type.includes("ERROR") || type.includes("FAILED") || type.includes("DENIED");
    }
    return type.includes(phase3.filter);
  }

  function payloadText(event) {
    try {
      return JSON.stringify(event.payload || {}, null, 2);
    } catch {
      return String(event.payload || "");
    }
  }

  function renderEvents() {
    const container = document.querySelector("#runtimeEventList");
    const count = document.querySelector("#runtimeEventCount");
    const navCount = document.querySelector("#runtimeEventNavCount");
    if (count) count.textContent = String(phase3.events.length);
    if (navCount) navCount.textContent = String(phase3.events.length);
    if (!container) return;

    const filtered = phase3.events.filter(matchesFilter);
    if (!filtered.length) {
      container.innerHTML = '<p class="dispatch-empty">No runtime events captured for this mission yet. The server worker synchronizes active CherryAgent and Hermes runs automatically.</p>';
      return;
    }

    container.innerHTML = filtered.slice().reverse().map((event) => {
      const severityClass = safeClass(event.severity || "INFO");
      const payload = payloadText(event);
      return `
        <article class="runtime-event ${severityClass}" data-runtime-event="${Number(event.id)}">
          <div class="runtime-event-rail"><i></i></div>
          <div class="runtime-event-body">
            <header>
              <div><strong>${escapeHtml(event.actor || runtimeName(event.runtime_key))}</strong><small>${escapeHtml(runtimeName(event.runtime_key))} · ${escapeHtml(event.dispatch_key || "")}</small></div>
              <div><span class="runtime-event-type">${escapeHtml(event.type || "RUNTIME_UPDATE")}</span><time>${escapeHtml(formatDateTime(event.occurred_at || event.created_at))}</time></div>
            </header>
            <p>${escapeHtml(event.message || "Runtime update")}</p>
            ${payload && payload !== "{}" ? `<details><summary>Evidence payload</summary><pre>${escapeHtml(payload)}</pre></details>` : ""}
          </div>
        </article>
      `;
    }).join("");
  }

  function appendEvent(event) {
    if (!event || !Number.isFinite(Number(event.id))) return;
    if (phase3.events.some((item) => Number(item.id) === Number(event.id))) return;
    phase3.events.push(event);
    phase3.events.sort((a, b) => Number(a.id) - Number(b.id));
    if (phase3.events.length > 500) phase3.events = phase3.events.slice(-500);
    renderEvents();
  }

  function closeStream() {
    if (phase3.source) phase3.source.close();
    phase3.source = null;
    phase3.missionKey = null;
    const status = document.querySelector("#eventStreamState");
    if (status) {
      status.textContent = "Disconnected";
      status.className = "stream-status disconnected";
    }
  }

  async function loadEvents(missionKey) {
    phase3.events = await api(`/api/missions/${encodeURIComponent(missionKey)}/runtime-events?limit=500`);
    renderEvents();
  }

  function startStream(missionKey) {
    closeStream();
    phase3.missionKey = missionKey;
    const latestId = phase3.events.reduce((max, event) => Math.max(max, Number(event.id) || 0), 0);
    const source = new EventSource(`/api/missions/${encodeURIComponent(missionKey)}/runtime-events/stream?after_id=${latestId}`);
    phase3.source = source;
    const status = document.querySelector("#eventStreamState");

    source.onopen = () => {
      if (phase3.missionKey !== missionKey || !status) return;
      status.textContent = "Live";
      status.className = "stream-status connected";
    };
    source.addEventListener("runtime.event", (message) => {
      if (phase3.missionKey !== missionKey) return;
      try {
        appendEvent(JSON.parse(message.data));
      } catch {
        // The durable backlog remains authoritative if a malformed frame arrives.
      }
    });
    source.addEventListener("heartbeat", () => {
      if (status && phase3.missionKey === missionKey) status.textContent = "Live";
    });
    source.onerror = () => {
      if (!status || phase3.missionKey !== missionKey) return;
      status.textContent = "Reconnecting";
      status.className = "stream-status reconnecting";
    };
  }

  async function selectMissionEvents(missionKey) {
    if (!missionKey || phase3.missionKey === missionKey) return;
    await loadEvents(missionKey);
    startStream(missionKey);
  }

  async function refreshWorkerState() {
    try {
      const worker = await api("/api/runtime-event-worker");
      const node = document.querySelector("#eventWorkerState");
      if (node) node.textContent = `${worker.status} · ${worker.interval_seconds}s · last batch ${worker.last_batch}`;
    } catch (error) {
      const node = document.querySelector("#eventWorkerState");
      if (node) node.textContent = error.message;
    }
  }

  function extendMissionSelection() {
    const phase2SelectMission = selectMission;
    selectMission = async function selectMissionWithRuntimeEvents(key) {
      await phase2SelectMission(key);
      await selectMissionEvents(key);
    };
  }

  async function initialize() {
    if (phase3.initialized) return;
    phase3.initialized = true;
    installUi();
    extendMissionSelection();
    await refreshWorkerState();
    setInterval(refreshWorkerState, 10000);

    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (state.selectedMission?.key) {
        await selectMissionEvents(state.selectedMission.key);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  window.addEventListener("beforeunload", closeStream);
  void initialize();
})();
