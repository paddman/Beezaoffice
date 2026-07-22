(() => {
  const roomsState = {
    rooms: [],
    selected: null,
    tab: "tasks",
    initialized: false,
    timer: null,
  };

  const roomEscape = (value = "") => typeof escapeHtml === "function"
    ? escapeHtml(value)
    : String(value).replace(/[&<>'"]/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    }[char]));
  const roomClass = (value = "") => typeof safeClass === "function"
    ? safeClass(value)
    : String(value).toLowerCase().replace(/[^a-z0-9_-]/g, "");
  const roomDate = (value) => typeof formatDateTime === "function" ? formatDateTime(value) : (value || "—");
  const lines = (value) => String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);

  function installUi() {
    if (document.querySelector("#agentRooms")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "agentRoomsNav";
    nav.innerHTML = 'Agent Rooms <span id="agentRoomsNavCount">0</span>';
    (document.querySelector("#registryNav") || document.querySelector("#organizationNav"))?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel agent-rooms-panel";
    panel.id = "agentRooms";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">VERSION 0.16.1 · AGENT ROOMS</p><h2>Digital Office Rooms</h2></div>
        <div class="runtime-header-state"><span id="agentRoomsState">Starting</span><b id="agentRoomsCount">0</b></div>
      </div>
      <p class="dispatch-intro">Every registered Agent receives a persistent personal room containing live work, direct messages, meetings, notes, evidence and replaceable visual assets.</p>
      <div class="agent-room-toolbar">
        <div class="agent-room-toolbar-group">
          <label>Department<select id="agentRoomDepartment"><option value="">All departments</option></select></label>
          <label>Availability<select id="agentRoomAvailability"><option value="">All states</option><option>AVAILABLE</option><option>BUSY</option><option>WAITING</option><option>OFFLINE</option><option>MAINTENANCE</option></select></label>
        </div>
        <div class="agent-room-toolbar-group"><span class="agent-room-placeholder-label">Mock assets are active until custom room art is added.</span><button class="secondary" id="agentRoomsRefresh">Refresh</button></div>
      </div>
      <div class="agent-room-layout">
        <aside class="agent-room-directory"><div id="agentRoomList" class="agent-room-list"></div></aside>
        <section id="agentRoomWorkspace" class="agent-room-workspace"><div class="agent-room-empty">Select an Agent Room.</div></section>
      </div>
      <p id="agentRoomMessage" class="agent-room-message"></p>
    `;
    (document.querySelector("#agentRegistry") || document.querySelector(".workforce-panel"))?.after(panel);

    const messageDialog = document.createElement("dialog");
    messageDialog.id = "agentRoomMessageDialog";
    messageDialog.innerHTML = `
      <form method="dialog" id="agentRoomMessageForm">
        <div class="dialog-head"><div><p class="eyebrow">DIRECT ROOM MESSAGE</p><h2>Message Agent</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="agent-room-dialog-grid">
          <label class="full">Subject<input id="agentRoomMessageSubject" required minlength="3" value="Direct request" /></label>
          <label class="full">Message<textarea id="agentRoomMessageBody" required minlength="1" placeholder="Ask for information or send context to this Agent."></textarea></label>
          <label>Type<select id="agentRoomMessageType"><option>REQUEST_INFO</option><option>FYI</option></select></label>
          <label><input id="agentRoomReplyRequired" type="checkbox" checked /> Reply required</label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Send message</button></div>
        <p id="agentRoomMessageFormState" class="form-message"></p>
      </form>
    `;
    document.body.append(messageDialog);

    const taskDialog = document.createElement("dialog");
    taskDialog.id = "agentRoomTaskDialog";
    taskDialog.innerHTML = `
      <form method="dialog" id="agentRoomTaskForm">
        <div class="dialog-head"><div><p class="eyebrow">PERSONAL WORK DESK</p><h2>Assign Work</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="agent-room-dialog-grid">
          <label class="full">Title<input id="agentRoomTaskTitle" required minlength="3" placeholder="Prepare the incident briefing" /></label>
          <label class="full">Objective<textarea id="agentRoomTaskObjective" required minlength="10" placeholder="Describe the outcome, constraints and evidence expected from this Agent."></textarea></label>
          <label>Priority<select id="agentRoomTaskPriority"><option>LOW</option><option selected>NORMAL</option><option>HIGH</option><option>CRITICAL</option></select></label>
          <label>Review<select id="agentRoomTaskReview"><option>AUTO</option><option>HUMAN</option></select></label>
          <label class="full">Expected outputs<textarea id="agentRoomTaskOutputs" placeholder="Executive summary\nEvidence list\nRecommended action"></textarea></label>
          <label class="full">Acceptance criteria<textarea id="agentRoomTaskAcceptance" placeholder="Sources cited\nNo unsupported claims\nAction owner identified"></textarea></label>
          <label><input id="agentRoomTaskDispatch" type="checkbox" checked /> Dispatch immediately</label>
          <label>Deadline<input id="agentRoomTaskDeadline" type="datetime-local" /></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Assign to Agent</button></div>
        <p id="agentRoomTaskFormState" class="form-message"></p>
      </form>
    `;
    document.body.append(taskDialog);

    const customizeDialog = document.createElement("dialog");
    customizeDialog.id = "agentRoomCustomizeDialog";
    customizeDialog.innerHTML = `
      <form method="dialog" id="agentRoomCustomizeForm">
        <div class="dialog-head"><div><p class="eyebrow">ROOM MOCK & ASSETS</p><h2>Customize Room</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="agent-room-dialog-grid">
          <label>Room title<input id="agentRoomTitle" required minlength="2" /></label>
          <label>Theme key<input id="agentRoomTheme" required minlength="2" /></label>
          <label class="full">Subtitle<input id="agentRoomSubtitle" /></label>
          <label>Status<select id="agentRoomStatus"><option>OPEN</option><option>FOCUS</option><option>AWAY</option><option>MAINTENANCE</option></select></label>
          <label>Visitor policy<select id="agentRoomVisitor"><option>PRIVATE</option><option>DEPARTMENT</option><option>TENANT</option></select></label>
          <label class="full">Status message<input id="agentRoomStatusMessage" /></label>
          <label class="full">Background asset<input id="agentRoomBackground" placeholder="/static/assets/agent-rooms/mira/background.webp" /></label>
          <label class="full">Avatar asset<input id="agentRoomAvatar" placeholder="/static/assets/agent-rooms/mira/avatar.webp" /></label>
          <label class="full">Foreground asset<input id="agentRoomForeground" placeholder="/static/assets/agent-rooms/mira/foreground.webp" /></label>
          <div id="agentRoomAssetGuide" class="agent-room-asset-guide full"></div>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Save room</button></div>
        <p id="agentRoomCustomizeState" class="form-message"></p>
      </form>
    `;
    document.body.append(customizeDialog);

    const noteDialog = document.createElement("dialog");
    noteDialog.id = "agentRoomNoteDialog";
    noteDialog.innerHTML = `
      <form method="dialog" id="agentRoomNoteForm">
        <div class="dialog-head"><div><p class="eyebrow">ROOM BOARD</p><h2>Add Note or Memory</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="agent-room-dialog-grid">
          <label>Type<select id="agentRoomNoteKind"><option>NOTE</option><option>MEMORY</option><option>REMINDER</option></select></label>
          <label><input id="agentRoomNotePinned" type="checkbox" /> Pin to room</label>
          <label class="full">Title<input id="agentRoomNoteTitle" required minlength="2" /></label>
          <label class="full">Content<textarea id="agentRoomNoteBody" placeholder="Context, reminder or curated memory for this Agent Room."></textarea></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Save note</button></div>
        <p id="agentRoomNoteState" class="form-message"></p>
      </form>
    `;
    document.body.append(noteDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#agentRoomsRefresh").addEventListener("click", () => loadRooms());
    panel.querySelector("#agentRoomDepartment").addEventListener("change", () => loadRooms());
    panel.querySelector("#agentRoomAvailability").addEventListener("change", () => loadRooms());
    messageDialog.querySelector("#agentRoomMessageForm").addEventListener("submit", sendMessage);
    taskDialog.querySelector("#agentRoomTaskForm").addEventListener("submit", assignTask);
    customizeDialog.querySelector("#agentRoomCustomizeForm").addEventListener("submit", saveCustomization);
    noteDialog.querySelector("#agentRoomNoteForm").addEventListener("submit", saveNote);

    document.addEventListener("click", (event) => {
      const legacy = event.target.closest("[data-agent]");
      if (legacy?.dataset.agent) openRoom(legacy.dataset.agent, true);
    });
    document.addEventListener("dblclick", (event) => {
      const registry = event.target.closest("[data-registry-agent]");
      if (registry?.dataset.registryAgent) openRoom(registry.dataset.registryAgent, true);
    });
  }

  function showMessage(text, type = "") {
    const node = document.querySelector("#agentRoomMessage");
    if (!node) return;
    node.textContent = text;
    node.className = `agent-room-message ${type}`;
  }

  function asset(value, fallback) {
    const text = String(value || "").trim();
    return text.startsWith("/static/") ? text : fallback;
  }

  function fillFilters() {
    const department = document.querySelector("#agentRoomDepartment");
    const current = department.value;
    const departments = [...new Set(roomsState.rooms.map((item) => item.agent?.department_key).filter(Boolean))].sort();
    department.innerHTML = '<option value="">All departments</option>' + departments.map((key) => `<option value="${roomEscape(key)}">${roomEscape(key.replace("dept:", ""))}</option>`).join("");
    department.value = departments.includes(current) ? current : "";
  }

  function renderRooms() {
    const list = document.querySelector("#agentRoomList");
    document.querySelector("#agentRoomsCount").textContent = String(roomsState.rooms.length);
    document.querySelector("#agentRoomsNavCount").textContent = String(roomsState.rooms.filter((item) => (item.counters?.tasks_active || 0) > 0).length);
    if (!roomsState.rooms.length) {
      list.innerHTML = '<p class="agent-room-filter-empty">No Agent Rooms match the current filters.</p>';
      return;
    }
    list.innerHTML = roomsState.rooms.map((item) => {
      const room = item.room || {};
      const agent = item.agent || {};
      const counters = item.counters || {};
      const background = asset(room.background_asset, "/static/assets/agent-room-placeholder.svg");
      const avatar = asset(room.avatar_asset, "/static/assets/agent-avatar-placeholder.svg");
      return `
        <button class="agent-room-card ${roomsState.selected?.room?.agent_key === room.agent_key ? "active" : ""}" data-agent-room="${roomEscape(room.agent_key)}">
          <div class="agent-room-card-scene" style="background-image:url('${roomEscape(background)}')">
            <img class="agent-room-card-avatar" src="${roomEscape(avatar)}" alt="${roomEscape(agent.name || room.agent_key)}" onerror="this.src='/static/assets/agent-avatar-placeholder.svg'" />
          </div>
          <div class="agent-room-card-body">
            <header><div><strong>${roomEscape(agent.name || room.title)}</strong><small>${roomEscape(agent.role || room.subtitle)}</small></div><span class="agent-room-state ${roomClass(agent.availability || room.room_status)}">${roomEscape(agent.availability || room.room_status)}</span></header>
            <footer><span>${roomEscape(agent.department_key || "")}</span><span>${Number(counters.tasks_active || 0)} active · ${Number(counters.inbox_unread || 0)} inbox</span></footer>
          </div>
        </button>
      `;
    }).join("");
    list.querySelectorAll("[data-agent-room]").forEach((button) => button.addEventListener("click", () => openRoom(button.dataset.agentRoom)));
  }

  function metric(label, value, detail) {
    return `<article class="agent-room-metric"><span>${roomEscape(label)}</span><strong>${roomEscape(value)}</strong><small>${roomEscape(detail)}</small></article>`;
  }

  function itemStatus(value) {
    return `<span class="agent-room-chip ${roomClass(value)}">${roomEscape(value || "—")}</span>`;
  }

  function renderTasks(data) {
    const tasks = data.tasks || [];
    return tasks.length ? `<div class="agent-room-grid">${tasks.map((task) => `
      <article class="agent-room-item"><header><div><strong>${roomEscape(task.title)}</strong><small>${roomEscape(task.key)} · ${roomEscape(task.target_runtime_key)}</small></div>${itemStatus(task.status)}</header><p>${roomEscape(task.objective)}</p><footer><span>${roomEscape(task.priority)} · ${roomEscape(task.review_policy)} review</span><span>${roomEscape(roomDate(task.deadline_at || task.updated_at))}</span></footer></article>
    `).join("")}</div>` : '<p class="agent-room-empty">No work has been assigned to this Agent.</p>';
  }

  function renderMessages(data) {
    const messages = data.messages || [];
    return messages.length ? `<div class="agent-room-grid">${messages.map((message) => `
      <article class="agent-room-item"><header><div><strong>${roomEscape(message.subject)}</strong><small>${roomEscape(message.source_identity)} → ${roomEscape(message.target_identity)}</small></div>${itemStatus(message.status)}</header><p>${roomEscape(message.body)}</p><footer><span>${roomEscape(message.type)}${message.reply_required ? " · Reply required" : ""}</span><span>${roomEscape(roomDate(message.created_at))}</span></footer></article>
    `).join("")}</div>` : '<p class="agent-room-empty">This Agent has no direct room messages.</p>';
  }

  function renderMeetings(data) {
    const meetings = data.meetings || [];
    return meetings.length ? `<div class="agent-room-grid">${meetings.map((meeting) => `
      <article class="agent-room-item"><header><div><strong>${roomEscape(meeting.title)}</strong><small>${roomEscape(meeting.key)} · ${roomEscape(meeting.decision_rule)}</small></div>${itemStatus(meeting.status)}</header><p>${roomEscape(meeting.objective)}</p><footer><span>Round ${Number(meeting.current_round || 0)}/${Number(meeting.max_rounds || 0)}</span><span>${roomEscape(roomDate(meeting.started_at || meeting.created_at))}</span></footer></article>
    `).join("")}</div>` : '<p class="agent-room-empty">No meetings are assigned to this Agent.</p>';
  }

  function renderNotes(data) {
    const notes = data.notes || [];
    return notes.length ? `<div class="agent-room-grid">${notes.map((note) => `
      <article class="agent-room-item"><header><div><strong>${roomEscape(note.title)}</strong><small>${roomEscape(note.kind)} · ${roomEscape(note.created_by)}</small></div>${itemStatus(note.pinned ? "PINNED" : "SAVED")}</header><p>${roomEscape(note.body)}</p><footer><span>${roomEscape(roomDate(note.updated_at))}</span><div class="agent-room-note-actions"><button class="danger-button" data-agent-room-note-delete="${roomEscape(note.key)}">Delete</button></div></footer></article>
    `).join("")}</div>` : '<p class="agent-room-empty">No notes or curated memory have been added.</p>';
  }

  function renderActivity(data) {
    const activity = data.activity || [];
    return activity.length ? `<div class="agent-room-grid">${activity.map((entry) => `
      <article class="agent-room-item"><header><div><strong>${roomEscape(entry.title)}</strong><small>${roomEscape(entry.type)} · ${roomEscape(entry.key)}</small></div>${itemStatus(entry.status)}</header><p>${roomEscape(entry.detail)}</p><footer><span>${roomEscape(roomDate(entry.at))}</span></footer></article>
    `).join("")}</div>` : '<p class="agent-room-empty">No room activity yet.</p>';
  }

  function renderTab(data) {
    if (roomsState.tab === "inbox") return renderMessages(data);
    if (roomsState.tab === "meetings") return renderMeetings(data);
    if (roomsState.tab === "notes") return renderNotes(data);
    if (roomsState.tab === "activity") return renderActivity(data);
    return renderTasks(data);
  }

  function renderWorkspace() {
    const container = document.querySelector("#agentRoomWorkspace");
    const data = roomsState.selected;
    if (!data) {
      container.innerHTML = '<div class="agent-room-empty">Select an Agent Room.</div>';
      return;
    }
    const room = data.room || {};
    const agent = data.agent || {};
    const counters = data.counters || {};
    const background = asset(room.background_asset, "/static/assets/agent-room-placeholder.svg");
    const avatar = asset(room.avatar_asset, "/static/assets/agent-avatar-placeholder.svg");
    const foreground = asset(room.foreground_asset, "");
    const hotspots = room.layout?.hotspots || [];
    container.innerHTML = `
      <div class="agent-room-head"><div><h3>${roomEscape(room.title)}</h3><p>${roomEscape(room.subtitle)} · ${roomEscape(agent.identity_key)}</p></div><div class="agent-room-actions"><button class="secondary" data-agent-room-action="message">Message</button><button class="primary" data-agent-room-action="task">Assign work</button><button class="secondary" data-agent-room-action="note">Add note</button><button class="secondary" data-agent-room-action="customize">Customize</button></div></div>
      <div class="agent-room-scene" style="background-image:url('${roomEscape(background)}')">
        <div class="agent-room-status-card"><strong>${roomEscape(agent.name)} · ${roomEscape(agent.role)}</strong><small>${roomEscape(room.status_message)}<br />${roomEscape(agent.availability)} · ${Number(agent.current_workload || 0)}/${Number(agent.max_concurrency || 0)} workload · Reliability ${Math.round(Number(agent.reliability_score || 0) * 100)}%</small></div>
        <img class="agent-room-avatar" src="${roomEscape(avatar)}" alt="${roomEscape(agent.name)}" onerror="this.src='/static/assets/agent-avatar-placeholder.svg'" />
        ${foreground ? `<img class="agent-room-foreground" src="${roomEscape(foreground)}" alt="" onerror="this.remove()" />` : ""}
        ${hotspots.map((hotspot) => `<span class="agent-room-hotspot" style="left:${Number(hotspot.x || 50)}%;top:${Number(hotspot.y || 50)}%">${roomEscape(hotspot.label || hotspot.key)}</span>`).join("")}
        <div class="agent-room-asset-card">Mock asset active · ${roomEscape(data.asset_guide?.background || "Add custom background later")}</div>
      </div>
      <div class="agent-room-metrics">
        ${metric("Active work", counters.tasks_active || 0, `${counters.tasks_total || 0} total tasks`)}
        ${metric("Completed", counters.tasks_completed || 0, `${counters.tasks_failed || 0} failed`)}
        ${metric("Inbox", counters.inbox_unread || 0, `${counters.messages_total || 0} messages`)}
        ${metric("Meetings", counters.meetings_active || 0, "Scheduled or running")}
        ${metric("Notes", counters.notes || 0, "Room memory board")}
        ${metric("Verified", counters.evaluation_pass || 0, `${counters.evaluation_warn || 0} warn · ${counters.evaluation_fail || 0} fail`)}
      </div>
      <div class="agent-room-tabs">${[["tasks","Work desk"],["inbox","Inbox"],["meetings","Meetings"],["notes","Notes & memory"],["activity","Activity"]].map(([key,label]) => `<button class="agent-room-tab ${roomsState.tab === key ? "active" : ""}" data-agent-room-tab="${key}">${label}</button>`).join("")}</div>
      <div id="agentRoomContent" class="agent-room-content">${renderTab(data)}</div>
    `;
    container.querySelectorAll("[data-agent-room-tab]").forEach((button) => button.addEventListener("click", () => {
      roomsState.tab = button.dataset.agentRoomTab;
      renderWorkspace();
    }));
    container.querySelectorAll("[data-agent-room-action]").forEach((button) => button.addEventListener("click", () => openAction(button.dataset.agentRoomAction)));
    container.querySelectorAll("[data-agent-room-note-delete]").forEach((button) => button.addEventListener("click", () => deleteNote(button.dataset.agentRoomNoteDelete)));
  }

  async function loadRooms(silent = false) {
    const params = new URLSearchParams();
    const department = document.querySelector("#agentRoomDepartment")?.value;
    const availability = document.querySelector("#agentRoomAvailability")?.value;
    if (department) params.set("department_key", department);
    if (availability) params.set("availability", availability);
    if (!silent) document.querySelector("#agentRoomsState").textContent = "Loading";
    try {
      roomsState.rooms = await operatorApi(`/api/agent-rooms?${params.toString()}`, {}, true);
      fillFilters();
      renderRooms();
      const selectedKey = roomsState.selected?.room?.agent_key;
      if (selectedKey && roomsState.rooms.some((item) => item.room?.agent_key === selectedKey)) {
        roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(selectedKey)}`, {}, true);
      } else if (roomsState.rooms.length) {
        roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(roomsState.rooms[0].room.agent_key)}`, {}, true);
      } else {
        roomsState.selected = null;
      }
      renderRooms();
      renderWorkspace();
      document.querySelector("#agentRoomsState").textContent = "Live";
      if (!silent) showMessage("Agent Rooms refreshed.", "success");
    } catch (error) {
      document.querySelector("#agentRoomsState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function openRoom(agentKey, scroll = false) {
    try {
      roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(agentKey)}`, {}, true);
      roomsState.tab = "tasks";
      renderRooms();
      renderWorkspace();
      if (scroll) document.querySelector("#agentRooms")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function openAction(action) {
    const data = roomsState.selected;
    if (!data) return;
    if (action === "message") {
      document.querySelector("#agentRoomMessageForm").reset();
      document.querySelector("#agentRoomMessageSubject").value = `Direct request for ${data.agent.name}`;
      document.querySelector("#agentRoomReplyRequired").checked = true;
      document.querySelector("#agentRoomMessageFormState").textContent = `Message will be delivered to ${data.agent.identity_key}.`;
      document.querySelector("#agentRoomMessageDialog").showModal();
    } else if (action === "task") {
      document.querySelector("#agentRoomTaskForm").reset();
      document.querySelector("#agentRoomTaskPriority").value = "NORMAL";
      document.querySelector("#agentRoomTaskReview").value = "AUTO";
      document.querySelector("#agentRoomTaskDispatch").checked = true;
      document.querySelector("#agentRoomTaskFormState").textContent = `Runtime: ${data.agent.preferred_runtime_key}`;
      document.querySelector("#agentRoomTaskDialog").showModal();
    } else if (action === "note") {
      document.querySelector("#agentRoomNoteForm").reset();
      document.querySelector("#agentRoomNoteState").textContent = `Save curated context in ${data.room.title}.`;
      document.querySelector("#agentRoomNoteDialog").showModal();
    } else {
      document.querySelector("#agentRoomTitle").value = data.room.title || "";
      document.querySelector("#agentRoomSubtitle").value = data.room.subtitle || "";
      document.querySelector("#agentRoomTheme").value = data.room.theme_key || "electric-office";
      document.querySelector("#agentRoomStatus").value = data.room.room_status || "OPEN";
      document.querySelector("#agentRoomVisitor").value = data.room.visitor_policy || "TENANT";
      document.querySelector("#agentRoomStatusMessage").value = data.room.status_message || "";
      document.querySelector("#agentRoomBackground").value = data.room.background_asset || "";
      document.querySelector("#agentRoomAvatar").value = data.room.avatar_asset || "";
      document.querySelector("#agentRoomForeground").value = data.room.foreground_asset || "";
      const guide = data.asset_guide || {};
      document.querySelector("#agentRoomAssetGuide").innerHTML = `<strong>Drop replacement files here:</strong><br />${roomEscape(guide.background || "")}<br />${roomEscape(guide.avatar || "")}<br />${roomEscape(guide.foreground || "")}<br />${roomEscape(guide.recommended_background || "")} · ${roomEscape(guide.recommended_avatar || "")}`;
      document.querySelector("#agentRoomCustomizeState").textContent = "Only /static/ asset paths are accepted.";
      document.querySelector("#agentRoomCustomizeDialog").showModal();
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    const data = roomsState.selected;
    if (!data) return;
    const stateNode = document.querySelector("#agentRoomMessageFormState");
    stateNode.textContent = "Sending…";
    try {
      roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(data.room.agent_key)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: document.querySelector("#agentRoomMessageSubject").value.trim(),
          body: document.querySelector("#agentRoomMessageBody").value.trim(),
          message_type: document.querySelector("#agentRoomMessageType").value,
          reply_required: document.querySelector("#agentRoomReplyRequired").checked,
        }),
      });
      stateNode.textContent = "Message delivered.";
      setTimeout(() => document.querySelector("#agentRoomMessageDialog").close(), 600);
      roomsState.tab = "inbox";
      renderWorkspace();
      await loadRooms(true);
    } catch (error) {
      stateNode.textContent = error.message;
    }
  }

  async function assignTask(event) {
    event.preventDefault();
    const data = roomsState.selected;
    if (!data) return;
    const stateNode = document.querySelector("#agentRoomTaskFormState");
    stateNode.textContent = "Assigning…";
    try {
      const deadline = document.querySelector("#agentRoomTaskDeadline").value;
      const response = await operatorApi(`/api/agent-rooms/${encodeURIComponent(data.room.agent_key)}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.querySelector("#agentRoomTaskTitle").value.trim(),
          objective: document.querySelector("#agentRoomTaskObjective").value.trim(),
          priority: document.querySelector("#agentRoomTaskPriority").value,
          review_policy: document.querySelector("#agentRoomTaskReview").value,
          auto_dispatch: document.querySelector("#agentRoomTaskDispatch").checked,
          expected_outputs: lines(document.querySelector("#agentRoomTaskOutputs").value),
          acceptance_criteria: lines(document.querySelector("#agentRoomTaskAcceptance").value),
          context: { assigned_from: "agent-room-ui" },
          deadline_at: deadline ? new Date(deadline).toISOString() : null,
        }),
      });
      roomsState.selected = response.room;
      stateNode.textContent = `${response.task.key} assigned.`;
      setTimeout(() => document.querySelector("#agentRoomTaskDialog").close(), 650);
      roomsState.tab = "tasks";
      renderWorkspace();
      await loadRooms(true);
    } catch (error) {
      stateNode.textContent = error.message;
    }
  }

  async function saveCustomization(event) {
    event.preventDefault();
    const data = roomsState.selected;
    if (!data) return;
    const stateNode = document.querySelector("#agentRoomCustomizeState");
    stateNode.textContent = "Saving…";
    try {
      roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(data.room.agent_key)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: document.querySelector("#agentRoomTitle").value.trim(),
          subtitle: document.querySelector("#agentRoomSubtitle").value.trim(),
          theme_key: document.querySelector("#agentRoomTheme").value.trim(),
          room_status: document.querySelector("#agentRoomStatus").value,
          visitor_policy: document.querySelector("#agentRoomVisitor").value,
          status_message: document.querySelector("#agentRoomStatusMessage").value.trim(),
          background_asset: document.querySelector("#agentRoomBackground").value.trim(),
          avatar_asset: document.querySelector("#agentRoomAvatar").value.trim(),
          foreground_asset: document.querySelector("#agentRoomForeground").value.trim(),
        }),
      });
      stateNode.textContent = "Room saved.";
      setTimeout(() => document.querySelector("#agentRoomCustomizeDialog").close(), 600);
      renderWorkspace();
      await loadRooms(true);
    } catch (error) {
      stateNode.textContent = error.message;
    }
  }

  async function saveNote(event) {
    event.preventDefault();
    const data = roomsState.selected;
    if (!data) return;
    const stateNode = document.querySelector("#agentRoomNoteState");
    stateNode.textContent = "Saving…";
    try {
      const response = await operatorApi(`/api/agent-rooms/${encodeURIComponent(data.room.agent_key)}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_kind: document.querySelector("#agentRoomNoteKind").value,
          title: document.querySelector("#agentRoomNoteTitle").value.trim(),
          body: document.querySelector("#agentRoomNoteBody").value.trim(),
          pinned: document.querySelector("#agentRoomNotePinned").checked,
        }),
      });
      roomsState.selected = response.room;
      stateNode.textContent = "Note saved.";
      setTimeout(() => document.querySelector("#agentRoomNoteDialog").close(), 600);
      roomsState.tab = "notes";
      renderWorkspace();
      await loadRooms(true);
    } catch (error) {
      stateNode.textContent = error.message;
    }
  }

  async function deleteNote(noteKey) {
    const data = roomsState.selected;
    if (!data || !window.confirm("Delete this Agent Room note?")) return;
    try {
      roomsState.selected = await operatorApi(`/api/agent-rooms/${encodeURIComponent(data.room.agent_key)}/notes/${encodeURIComponent(noteKey)}`, { method: "DELETE" });
      roomsState.tab = "notes";
      renderWorkspace();
      await loadRooms(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function startPolling() {
    if (roomsState.timer) clearInterval(roomsState.timer);
    roomsState.timer = setInterval(() => {
      if (!document.hidden && !document.querySelector("dialog[open]")) void loadRooms(true);
    }, 15000);
  }

  function init() {
    if (roomsState.initialized) return;
    roomsState.initialized = true;
    installUi();
    startPolling();
    void loadRooms();
  }

  init();
})();
