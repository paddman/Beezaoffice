(() => {
  const phase5 = {
    missionKey: null,
    meetings: [],
    selected: null,
    timer: null,
    initialized: false,
  };

  function runtimeOptions(selected = "") {
    return state.runtimes.map((runtime) => (
      `<option value="${escapeHtml(runtime.key)}" ${runtime.key === selected ? "selected" : ""} ${runtime.configured ? "" : "disabled"}>${escapeHtml(runtime.name)}${runtime.configured ? "" : " · not configured"}</option>`
    )).join("");
  }

  function firstConfiguredRuntime(index = 0) {
    const configured = state.runtimes.filter((runtime) => runtime.configured);
    return configured[index % Math.max(configured.length, 1)]?.key || state.runtimes[0]?.key || "";
  }

  function installUi() {
    if (document.querySelector("#meetingManager")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "meetingNav";
    nav.innerHTML = 'Meetings <span id="meetingNavCount">0</span>';
    document.querySelector("#collaborationNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel meeting-panel";
    panel.id = "meetingManager";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 5 · AGENT MEETING MANAGER</p><h2>Structured Decision Rooms</h2></div>
        <div class="meeting-header-state"><span id="meetingPanelState">Ready</span><b id="meetingCount">0</b></div>
      </div>
      <p class="dispatch-intro">Run bounded, turn-based meetings across agent runtimes. Every room has an agenda, role-specific contributions, confidence scores, a human decision and action items routed into the Collaboration Bus.</p>
      <div class="meeting-worker-state"><span>Meeting worker</span><strong id="meetingWorkerState">Starting</strong></div>
      <div id="meetingStats" class="meeting-stats"></div>
      <div class="meeting-layout">
        <section class="meeting-list">
          <div class="meeting-section-head"><div><strong>Mission meetings</strong><small>Discussion rooms and decision state</small></div><button class="primary" id="newMeeting">+ New meeting</button></div>
          <div id="meetingList" class="meeting-list-body"></div>
        </section>
        <section class="meeting-room">
          <div class="meeting-section-head"><div><strong>Meeting room</strong><small>Agenda → turns → decision → action items</small></div><div class="meeting-buttons" id="meetingActions"></div></div>
          <div id="meetingRoomBody" class="meeting-room-body"><p class="meeting-empty">Select or create a structured meeting.</p></div>
        </section>
      </div>
    `;
    document.querySelector("#collaborationBus")?.after(panel);

    const createDialog = document.createElement("dialog");
    createDialog.id = "meetingDialog";
    createDialog.innerHTML = `
      <form method="dialog" id="meetingForm">
        <div class="dialog-head"><div><p class="eyebrow">BEEZA MEETING MANAGER</p><h2>Create Structured Meeting</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="meeting-form-grid">
          <label class="full">Meeting title<input id="meetingTitle" required minlength="3" placeholder="Incident remediation decision" /></label>
          <label class="full">Objective<textarea id="meetingObjective" required minlength="10" placeholder="Evaluate the evidence, challenge the remediation options and decide the safest action plan."></textarea></label>
          <label class="full">Agenda<textarea id="meetingAgenda" placeholder="Review verified evidence\nCompare options and risks\nSelect decision\nAssign action items"></textarea></label>
          <label>Maximum rounds<select id="meetingRounds"><option value="1">1</option><option value="2" selected>2</option><option value="3">3</option><option value="4">4</option><option value="5">5</option></select></label>
          <label>Decision rule<select id="meetingRule"><option>EXECUTIVE</option><option>CONSENSUS</option><option>MAJORITY</option></select></label>
          <label>Moderator identity<input id="meetingModerator" value="agent:Beeza Moderator" required /></label>
          <label>Decision owner<input id="meetingOwner" value="agent:Beeza Commander" required /></label>
        </div>
        <div class="meeting-section-head"><div><strong>Participants</strong><small>Speaking order is top to bottom</small></div><button type="button" class="secondary" id="addMeetingParticipant">+ Participant</button></div>
        <div id="meetingParticipantEditor" class="participant-editor"></div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create meeting</button></div>
        <p id="meetingFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(createDialog);

    const decisionDialog = document.createElement("dialog");
    decisionDialog.id = "meetingDecisionDialog";
    decisionDialog.innerHTML = `
      <form method="dialog" id="meetingDecisionForm">
        <div class="dialog-head"><div><p class="eyebrow">HUMAN DECISION GATE</p><h2>Record Meeting Decision</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="meeting-form-grid">
          <label class="full">Decision title<input id="decisionTitle" required minlength="3" placeholder="Approve staged remediation" /></label>
          <label class="full">Rationale<textarea id="decisionRationale" required minlength="5" placeholder="State why this option was selected, which evidence supports it, and which risks remain."></textarea></label>
          <label>Status<select id="decisionStatus"><option>ACCEPTED</option><option>OVERRIDDEN</option><option>REJECTED</option></select></label>
          <label>Confidence<input id="decisionConfidence" type="number" min="0" max="1" step="0.01" value="0.80" required /></label>
          <label class="full">Decided by<input id="decisionBy" value="agent:Beeza Commander" required /></label>
        </div>
        <div class="meeting-section-head"><div><strong>Action items</strong><small>Accepted decisions become Collaboration Bus tasks</small></div><button type="button" class="secondary" id="addDecisionAction">+ Action item</button></div>
        <div id="decisionActionEditor" class="action-item-editor"></div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Record decision</button></div>
        <p id="decisionFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(decisionDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#newMeeting").addEventListener("click", openMeetingDialog);
    createDialog.querySelector("#addMeetingParticipant").addEventListener("click", () => addParticipantRow());
    createDialog.querySelector("#meetingForm").addEventListener("submit", createMeeting);
    decisionDialog.querySelector("#addDecisionAction").addEventListener("click", () => addActionRow());
    decisionDialog.querySelector("#meetingDecisionForm").addEventListener("submit", submitDecision);
  }

  function lineValues(value) {
    return String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function addParticipantRow(identity = "agent:Specialist", role = "DOMAIN", runtimeKey = "", instructions = "") {
    const editor = document.querySelector("#meetingParticipantEditor");
    if (!editor) return;
    const row = document.createElement("div");
    row.className = "participant-row";
    row.innerHTML = `
      <input class="meeting-participant-identity" value="${escapeHtml(identity)}" required placeholder="agent identity" />
      <select class="meeting-participant-runtime" required>${runtimeOptions(runtimeKey || firstConfiguredRuntime(editor.children.length))}</select>
      <select class="meeting-participant-role"><option>MODERATOR</option><option>EXECUTIVE</option><option>DOMAIN</option><option>CRITIC</option><option>PMO</option><option>OBSERVER</option></select>
      <button type="button" class="danger-button meeting-remove-row">×</button>
      <input class="meeting-participant-instructions" value="${escapeHtml(instructions)}" placeholder="role-specific instruction (optional)" style="grid-column:1 / span 3" />
    `;
    row.querySelector(".meeting-participant-role").value = role;
    row.querySelector(".meeting-remove-row").addEventListener("click", () => row.remove());
    editor.append(row);
  }

  function addActionRow(item = {}) {
    const editor = document.querySelector("#decisionActionEditor");
    if (!editor) return;
    const runtimeKey = item.target_runtime_key || firstConfiguredRuntime(editor.children.length);
    const row = document.createElement("div");
    row.className = "action-item-row";
    row.innerHTML = `
      <input class="decision-action-title" value="${escapeHtml(item.title || "")}" required placeholder="Action title" />
      <select class="decision-action-runtime" required>${runtimeOptions(runtimeKey)}</select>
      <input class="decision-action-target" value="${escapeHtml(item.target_identity || (runtimeKey ? `runtime:${runtimeKey}` : ""))}" placeholder="Target agent/runtime" />
      <button type="button" class="danger-button decision-remove-row">×</button>
      <textarea class="decision-action-objective" required minlength="10" placeholder="Execution objective">${escapeHtml(item.objective || "")}</textarea>
      <input class="decision-action-owner" value="${escapeHtml(item.owner_identity || "")}" placeholder="Owner identity" />
      <input class="decision-action-deadline" type="datetime-local" />
      <select class="decision-action-priority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select>
    `;
    row.querySelector(".decision-action-priority").value = item.priority || state.selectedMission?.priority || "NORMAL";
    row.querySelector(".decision-remove-row").addEventListener("click", () => row.remove());
    editor.append(row);
  }

  function renderMeetingStats() {
    const counts = { total: phase5.meetings.length, running: 0, awaiting: 0, completed: 0, draft: 0 };
    phase5.meetings.forEach((meeting) => {
      if (meeting.status === "RUNNING") counts.running += 1;
      if (meeting.status === "AWAITING_DECISION") counts.awaiting += 1;
      if (meeting.status === "COMPLETED") counts.completed += 1;
      if (["DRAFT", "SCHEDULED"].includes(meeting.status)) counts.draft += 1;
    });
    const cards = [
      ["Total", counts.total], ["Draft", counts.draft], ["Running", counts.running],
      ["Decision", counts.awaiting], ["Completed", counts.completed],
    ];
    const container = document.querySelector("#meetingStats");
    if (container) container.innerHTML = cards.map(([label, value]) => `<article class="meeting-stat"><span>${label}</span><strong>${value}</strong></article>`).join("");
    document.querySelector("#meetingCount").textContent = String(counts.total);
    document.querySelector("#meetingNavCount").textContent = String(counts.running + counts.awaiting);
  }

  function renderMeetingList() {
    const container = document.querySelector("#meetingList");
    if (!container) return;
    if (!phase5.meetings.length) {
      container.innerHTML = '<p class="meeting-empty">No meetings for this mission.</p>';
      return;
    }
    container.innerHTML = phase5.meetings.map((meeting) => {
      const statusClass = safeClass(meeting.status);
      const progress = `${meeting.completed_turns || 0}/${meeting.total_turns || 0} turns`;
      return `
        <button class="meeting-card ${phase5.selected?.key === meeting.key ? "active" : ""}" data-meeting-key="${escapeHtml(meeting.key)}">
          <header><strong>${escapeHtml(meeting.title)}</strong><span class="meeting-status ${statusClass}">${escapeHtml(meeting.status)}</span></header>
          <p>${escapeHtml(meeting.objective)}</p>
          <footer><span>${escapeHtml(meeting.key)} · ${meeting.participant_count || 0} participants</span><span>Round ${meeting.current_round}/${meeting.max_rounds} · ${progress}</span></footer>
        </button>
      `;
    }).join("");
    container.querySelectorAll("[data-meeting-key]").forEach((button) => {
      button.addEventListener("click", () => selectMeeting(button.dataset.meetingKey));
    });
  }

  function contributionSummary(turn) {
    const body = turn.contribution || {};
    return body.summary || body.recommendation || body.error || body.blocker || "Waiting for contribution.";
  }

  function participantFor(turn) {
    return phase5.selected?.participants?.find((item) => item.key === turn.participant_key);
  }

  function renderMeetingActions(meeting) {
    const container = document.querySelector("#meetingActions");
    if (!container) return;
    const actions = [];
    if (["DRAFT", "SCHEDULED"].includes(meeting.status)) actions.push(`<button class="primary" data-meeting-action="start">Start</button>`);
    if (meeting.status === "RUNNING") {
      actions.push(`<button class="secondary" data-meeting-action="tick">Run turn</button>`);
      actions.push(`<button class="primary" data-meeting-action="decision">Executive override</button>`);
      actions.push(`<button class="danger-button" data-meeting-action="cancel">Cancel</button>`);
    }
    if (meeting.status === "AWAITING_DECISION") actions.push(`<button class="primary" data-meeting-action="decision">Record decision</button>`);
    container.innerHTML = actions.join("");
    container.querySelectorAll("[data-meeting-action]").forEach((button) => {
      button.addEventListener("click", () => meetingAction(button.dataset.meetingAction));
    });
  }

  function renderMeetingRoom() {
    const container = document.querySelector("#meetingRoomBody");
    const meeting = phase5.selected;
    if (!container) return;
    if (!meeting) {
      container.innerHTML = '<p class="meeting-empty">Select or create a structured meeting.</p>';
      document.querySelector("#meetingActions").innerHTML = "";
      return;
    }
    renderMeetingActions(meeting);
    const agenda = meeting.agenda?.length ? meeting.agenda.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>Resolve the meeting objective</li>";
    const participants = (meeting.participants || []).map((item) => `<span class="meeting-participant"><b>${escapeHtml(item.role)}</b> · ${escapeHtml(item.identity)} · ${escapeHtml(runtimeName(item.runtime_key))}</span>`).join("");
    const turns = (meeting.turns || []).map((turn, index) => {
      const participant = participantFor(turn);
      const summary = contributionSummary(turn);
      return `
        <article class="meeting-turn">
          <div class="meeting-turn-index">${index + 1}</div>
          <div class="meeting-turn-card">
            <header><div><strong>${escapeHtml(participant?.identity || turn.participant_key)}</strong><small>${escapeHtml(participant?.role || "PARTICIPANT")} · ${escapeHtml(runtimeName(participant?.runtime_key || ""))} · Round ${turn.round_number}</small></div><span class="meeting-status ${safeClass(turn.status)}">${escapeHtml(turn.status)}</span></header>
            <p>${escapeHtml(summary)}</p>
            ${turn.confidence !== null && turn.confidence !== undefined ? `<span class="meeting-confidence">Confidence ${Number(turn.confidence).toFixed(2)}</span>` : ""}
          </div>
        </article>
      `;
    }).join("") || '<p class="meeting-empty">Meeting has not started.</p>';
    const decisions = (meeting.decisions || []).slice().reverse().map((decision) => `
      <article class="meeting-decision-card">
        <header><strong>${escapeHtml(decision.title)}</strong><span class="meeting-status ${safeClass(decision.status)}">${escapeHtml(decision.status)}</span></header>
        <p>${escapeHtml(decision.rationale)}</p>
        <footer><span>By ${escapeHtml(decision.decided_by)}</span><span>Confidence ${Number(decision.confidence).toFixed(2)}</span><span>${decision.generated_task_keys?.length || 0} action tasks</span></footer>
      </article>
    `).join("") || '<p class="meeting-empty">No decision recorded.</p>';
    container.innerHTML = `
      <div class="meeting-room-title"><div><h3>${escapeHtml(meeting.title)}</h3><p>${escapeHtml(meeting.objective)}</p></div><span class="meeting-status ${safeClass(meeting.status)}">${escapeHtml(meeting.status)}</span></div>
      <div class="meeting-meta">
        <div><span>Meeting</span><strong>${escapeHtml(meeting.key)}</strong></div>
        <div><span>Round</span><strong>${meeting.current_round} / ${meeting.max_rounds}</strong></div>
        <div><span>Decision rule</span><strong>${escapeHtml(meeting.decision_rule)}</strong></div>
        <div><span>Owner</span><strong>${escapeHtml(meeting.owner_identity)}</strong></div>
      </div>
      <div class="meeting-agenda"><strong>Agenda</strong><ol>${agenda}</ol></div>
      <div class="meeting-participants">${participants}</div>
      ${meeting.summary ? `<div class="meeting-summary">${escapeHtml(meeting.summary)}</div>` : ""}
      <div class="meeting-turns"><h4>Speaking turns</h4>${turns}</div>
      <div class="meeting-decision"><h4>Decision record</h4>${decisions}</div>
    `;
  }

  function renderMeetings() {
    renderMeetingStats();
    renderMeetingList();
    renderMeetingRoom();
  }

  async function loadMeetings(missionKey, silent = false) {
    if (!missionKey) return;
    if (!silent) document.querySelector("#meetingPanelState").textContent = "Loading";
    try {
      const meetings = await api(`/api/missions/${encodeURIComponent(missionKey)}/meetings`);
      phase5.missionKey = missionKey;
      phase5.meetings = meetings;
      if (phase5.selected) {
        const stillExists = meetings.some((item) => item.key === phase5.selected.key);
        if (stillExists) phase5.selected = await api(`/api/meetings/${encodeURIComponent(phase5.selected.key)}`);
        else phase5.selected = null;
      }
      renderMeetings();
      document.querySelector("#meetingPanelState").textContent = "Live";
    } catch (error) {
      if (!silent) document.querySelector("#meetingPanelState").textContent = error.message;
    }
  }

  async function selectMeeting(key) {
    phase5.selected = await api(`/api/meetings/${encodeURIComponent(key)}`);
    renderMeetings();
  }

  async function refreshMeetingWorker() {
    try {
      const worker = await api("/api/meeting-worker");
      document.querySelector("#meetingWorkerState").textContent = `${worker.status} · ${worker.interval_seconds}s · processed ${worker.last_processed} · timeout ${Math.round(worker.turn_timeout_seconds / 60)}m${worker.last_error ? ` · ${worker.last_error}` : ""}`;
    } catch (error) {
      document.querySelector("#meetingWorkerState").textContent = error.message;
    }
  }

  function openMeetingDialog() {
    const mission = state.selectedMission;
    if (!mission) return;
    document.querySelector("#meetingForm").reset();
    document.querySelector("#meetingOwner").value = `agent:${mission.commander}`;
    document.querySelector("#meetingModerator").value = "agent:Beeza Moderator";
    document.querySelector("#meetingFormMessage").textContent = `Mission ${mission.key}`;
    const editor = document.querySelector("#meetingParticipantEditor");
    editor.innerHTML = "";
    addParticipantRow("agent:Beeza Moderator", "MODERATOR", firstConfiguredRuntime(0), "Keep the meeting on agenda and summarize disagreements.");
    addParticipantRow("agent:Domain Specialist", "DOMAIN", firstConfiguredRuntime(1), "Use evidence and propose feasible options.");
    addParticipantRow("agent:Devil's Advocate", "CRITIC", firstConfiguredRuntime(2), "Challenge assumptions and expose failure modes.");
    addParticipantRow("agent:PMO", "PMO", firstConfiguredRuntime(3), "Convert the accepted direction into owners and deliverables.");
    document.querySelector("#meetingDialog").showModal();
  }

  async function createMeeting(event) {
    event.preventDefault();
    const mission = state.selectedMission;
    if (!mission) return;
    const rows = [...document.querySelectorAll("#meetingParticipantEditor .participant-row")];
    const participants = rows.map((row) => ({
      identity: row.querySelector(".meeting-participant-identity").value.trim(),
      runtime_key: row.querySelector(".meeting-participant-runtime").value,
      role: row.querySelector(".meeting-participant-role").value,
      instructions: row.querySelector(".meeting-participant-instructions").value.trim(),
      required: true,
    }));
    const message = document.querySelector("#meetingFormMessage");
    message.textContent = "Creating structured meeting…";
    try {
      const meeting = await operatorApi(`/api/missions/${encodeURIComponent(mission.key)}/meetings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.querySelector("#meetingTitle").value.trim(),
          objective: document.querySelector("#meetingObjective").value.trim(),
          agenda: lineValues(document.querySelector("#meetingAgenda").value),
          max_rounds: Number(document.querySelector("#meetingRounds").value),
          decision_rule: document.querySelector("#meetingRule").value,
          moderator_identity: document.querySelector("#meetingModerator").value.trim(),
          owner_identity: document.querySelector("#meetingOwner").value.trim(),
          participants,
        }),
      });
      phase5.selected = meeting;
      message.textContent = `${meeting.key} created.`;
      setTimeout(() => document.querySelector("#meetingDialog").close(), 650);
      await loadMeetings(mission.key);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function openDecisionDialog() {
    const meeting = phase5.selected;
    if (!meeting) return;
    document.querySelector("#meetingDecisionForm").reset();
    document.querySelector("#decisionBy").value = meeting.owner_identity || `agent:${state.selectedMission?.commander || "Beeza Commander"}`;
    document.querySelector("#decisionStatus").value = meeting.status === "RUNNING" ? "OVERRIDDEN" : "ACCEPTED";
    document.querySelector("#decisionFormMessage").textContent = `${meeting.key} · ${meeting.decision_rule}`;
    document.querySelector("#decisionActionEditor").innerHTML = "";
    addActionRow({ priority: state.selectedMission?.priority || "NORMAL" });
    document.querySelector("#meetingDecisionDialog").showModal();
  }

  async function submitDecision(event) {
    event.preventDefault();
    const meeting = phase5.selected;
    if (!meeting) return;
    const actionRows = [...document.querySelectorAll("#decisionActionEditor .action-item-row")];
    const actionItems = actionRows.map((row) => {
      const deadline = row.querySelector(".decision-action-deadline").value;
      return {
        title: row.querySelector(".decision-action-title").value.trim(),
        objective: row.querySelector(".decision-action-objective").value.trim(),
        target_runtime_key: row.querySelector(".decision-action-runtime").value,
        target_identity: row.querySelector(".decision-action-target").value.trim() || null,
        owner_identity: row.querySelector(".decision-action-owner").value.trim() || null,
        priority: row.querySelector(".decision-action-priority").value,
        review_policy: "AUTO",
        expected_outputs: ["Verified completion result", "Evidence and blockers"],
        acceptance_criteria: ["Result is evidence-backed", "Completion state is explicit"],
        deadline_at: deadline ? new Date(deadline).toISOString() : null,
      };
    }).filter((item) => item.title && item.objective);
    const message = document.querySelector("#decisionFormMessage");
    message.textContent = "Recording decision and creating action items…";
    try {
      phase5.selected = await operatorApi(`/api/meetings/${encodeURIComponent(meeting.key)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.querySelector("#decisionTitle").value.trim(),
          rationale: document.querySelector("#decisionRationale").value.trim(),
          status: document.querySelector("#decisionStatus").value,
          decided_by: document.querySelector("#decisionBy").value.trim(),
          confidence: Number(document.querySelector("#decisionConfidence").value),
          votes: {},
          action_items: document.querySelector("#decisionStatus").value === "REJECTED" ? [] : actionItems,
        }),
      });
      message.textContent = "Decision recorded.";
      setTimeout(() => document.querySelector("#meetingDecisionDialog").close(), 650);
      await loadMeetings(phase5.missionKey);
      if (typeof loadCollaboration === "function") await loadCollaboration(phase5.missionKey, true);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  async function meetingAction(action) {
    const meeting = phase5.selected;
    if (!meeting) return;
    const statusNode = document.querySelector("#meetingPanelState");
    try {
      if (action === "decision") {
        openDecisionDialog();
        return;
      }
      if (action === "cancel") {
        if (!window.confirm(`Cancel ${meeting.key}? Active remote work may finish but no new turns will start.`)) return;
        phase5.selected = await operatorApi(`/api/meetings/${encodeURIComponent(meeting.key)}/cancel?note=${encodeURIComponent("Cancelled by Beeza operator")}`, { method: "POST" });
      } else {
        statusNode.textContent = action === "start" ? "Starting meeting" : "Advancing meeting";
        const result = await operatorApi(`/api/meetings/${encodeURIComponent(meeting.key)}/${action === "start" ? "start" : "tick"}`, { method: "POST" });
        phase5.selected = result.meeting || result;
      }
      await loadMeetings(phase5.missionKey);
      statusNode.textContent = "Live";
    } catch (error) {
      statusNode.textContent = error.message;
    }
  }

  function extendMissionSelection() {
    const phase4SelectMission = selectMission;
    selectMission = async function selectMissionWithMeetings(key) {
      await phase4SelectMission(key);
      phase5.selected = null;
      await loadMeetings(key);
    };
  }

  function startPolling() {
    if (phase5.timer) clearInterval(phase5.timer);
    phase5.timer = setInterval(async () => {
      if (document.hidden || !state.selectedMission) return;
      await loadMeetings(state.selectedMission.key, true);
      await refreshMeetingWorker();
    }, 3000);
  }

  async function initialize() {
    if (phase5.initialized) return;
    phase5.initialized = true;
    installUi();
    extendMissionSelection();
    await refreshMeetingWorker();
    startPolling();
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (state.selectedMission?.key) {
        await loadMeetings(state.selectedMission.key);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  void initialize();
})();
