(() => {
  const phase9 = {
    status: null,
    evaluations: [],
    replays: [],
    selected: null,
    selectedDetail: null,
    initialized: false,
    timer: null,
    lastMissionKey: null,
  };

  function installUi() {
    if (document.querySelector("#evaluationCenter")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "evaluationNav";
    nav.innerHTML = 'Evaluation <span id="evaluationNavCount">0</span>';
    document.querySelector("#schedulerNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel evaluation-panel";
    panel.id = "evaluationCenter";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 9 · EVALUATION, VERIFICATION & REPLAY</p><h2>Evidence Quality Control</h2></div>
        <div class="evaluation-header-state"><span id="evaluationState">Starting</span><b id="evaluationCount">0</b></div>
      </div>
      <p class="dispatch-intro">A runtime saying “completed” is not enough. Beeza checks acceptance coverage, supporting evidence, execution provenance, consistency, reproducibility and risk disclosure before recommending acceptance, human review or replay.</p>
      <div class="evaluation-toolbar">
        <span id="evaluationPolicySummary">Loading evaluation policy…</span>
        <div class="evaluation-toolbar-actions"><button class="secondary" id="evaluationTick">Run evaluator</button><button class="secondary" id="evaluationRefresh">Refresh</button><button class="primary" id="evaluationNewReplay">+ Replay task</button></div>
      </div>
      <div id="evaluationStats" class="evaluation-stats"></div>
      <div class="evaluation-layout">
        <section class="evaluation-box">
          <div class="evaluation-box-head"><div><strong>Evaluation runs</strong><small>Latest evidence decision per completed work package</small></div><span id="evaluationMissionFilter">All missions</span></div>
          <div id="evaluationList" class="evaluation-list"></div>
        </section>
        <section class="evaluation-box">
          <div class="evaluation-box-head"><div><strong>Verification evidence</strong><small>Score components, findings and provenance</small></div><span id="evaluationDetailState">Select a run</span></div>
          <div id="evaluationDetail" class="evaluation-detail"><p class="evaluation-empty">Select an evaluation run.</p></div>
        </section>
      </div>
      <section class="evaluation-replays">
        <header><strong>Replay and comparison history</strong><span id="evaluationReplayCount">0 replay runs</span></header>
        <div id="evaluationReplayList" class="evaluation-replay-list"></div>
      </section>
      <p id="evaluationMessage" class="evaluation-message"></p>
    `;
    document.querySelector("#schedulerRouter")?.after(panel);

    const replayDialog = document.createElement("dialog");
    replayDialog.id = "evaluationReplayDialog";
    replayDialog.innerHTML = `
      <form method="dialog" id="evaluationReplayForm">
        <div class="dialog-head"><div><p class="eyebrow">CONTROLLED RE-EXECUTION</p><h2>Replay Task</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="evaluation-form-grid">
          <label class="full">Source task<select id="replaySourceTask" required></select></label>
          <label>Replay mode<select id="replayMode"><option value="REROUTE">REROUTE · choose a different route</option><option value="FAILOVER">FAILOVER · exclude failed route</option><option value="SAME">SAME · reproduce original route</option></select></label>
          <label>Preferred runtime<select id="replayRuntime"><option value="">Automatic / original</option></select></label>
          <label class="full">Target identity<input id="replayTargetIdentity" placeholder="Optional: agent:yuna" /></label>
          <label class="full">Reason<textarea id="replayReason" required minlength="3" placeholder="Re-run with a different agent/runtime to verify the conclusion and compare evidence quality."></textarea></label>
        </div>
        <div class="scheduler-checks"><label><input id="replayAutoDispatch" type="checkbox" checked /> Auto-dispatch replay</label></div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create replay</button></div>
        <p id="evaluationReplayMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(replayDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#evaluationTick").addEventListener("click", runEvaluationTick);
    panel.querySelector("#evaluationRefresh").addEventListener("click", () => loadEvaluation(false));
    panel.querySelector("#evaluationNewReplay").addEventListener("click", () => openReplayDialog());
    replayDialog.querySelector("#evaluationReplayForm").addEventListener("submit", createReplay);
  }

  function showMessage(message, type = "") {
    const node = document.querySelector("#evaluationMessage");
    if (!node) return;
    node.textContent = message;
    node.className = `evaluation-message ${type}`;
  }

  function missionKey() {
    return state.selectedMission?.key || "";
  }

  function renderStats() {
    const stats = phase9.status?.stats || {};
    const worker = phase9.status?.worker || {};
    const evaluations = stats.evaluations || {};
    const replays = stats.replays || {};
    const cards = [
      ["Pass rate", `${Math.round(Number(stats.pass_rate || 0) * 100)}%`, `${evaluations.PASS || 0} passed`],
      ["Average score", `${Math.round(Number(stats.average_score || 0) * 100)}%`, `${stats.total_evaluations || 0} evaluations`],
      ["Warnings", evaluations.WARN || 0, "Human review recommended"],
      ["Failures", evaluations.FAIL || 0, "Revise or replay"],
      ["Human review", stats.open_human_review || 0, "Tasks awaiting decision"],
      ["Replays", stats.total_replays || 0, `${replays.RUNNING || 0} running`],
    ];
    document.querySelector("#evaluationStats").innerHTML = cards.map(([label, value, detail]) => `<article class="evaluation-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
    document.querySelector("#evaluationCount").textContent = String((evaluations.WARN || 0) + (evaluations.FAIL || 0));
    document.querySelector("#evaluationNavCount").textContent = String((evaluations.WARN || 0) + (evaluations.FAIL || 0) + (stats.open_human_review || 0));
    document.querySelector("#evaluationState").textContent = worker.status || "starting";
    const policy = stats.policy || {};
    document.querySelector("#evaluationPolicySummary").textContent = `${policy.name || "Evidence baseline"} · pass ${Math.round(Number(policy.pass_score || 0) * 100)}% · warn ${Math.round(Number(policy.warn_score || 0) * 100)}% · minimum evidence ${policy.minimum_evidence ?? 2} · worker ${worker.status || "starting"}`;
  }

  function renderEvaluationList() {
    const container = document.querySelector("#evaluationList");
    const currentMission = missionKey();
    document.querySelector("#evaluationMissionFilter").textContent = currentMission || "All missions";
    if (!phase9.evaluations.length) {
      container.innerHTML = '<p class="evaluation-empty">No evaluation runs for the current mission.</p>';
      return;
    }
    container.innerHTML = phase9.evaluations.map((item) => `
      <button class="evaluation-card ${phase9.selected?.key === item.key ? "active" : ""}" data-evaluation-key="${escapeHtml(item.key)}">
        <header><div><strong>${escapeHtml(item.task_key)}</strong><small>${escapeHtml(item.mission_key)} · ${escapeHtml(item.key)}</small></div><span class="evaluation-status ${safeClass(item.status)}">${escapeHtml(item.status)}</span></header>
        <p>${escapeHtml(item.recommendation.replaceAll("_", " "))} · ${item.evidence_count} supporting evidence items</p>
        <footer><span>Score ${Math.round(Number(item.score || 0) * 100)}%</span><span>${escapeHtml(formatDateTime(item.created_at))}</span></footer>
      </button>
    `).join("");
    container.querySelectorAll("[data-evaluation-key]").forEach((button) => button.addEventListener("click", () => selectEvaluation(button.dataset.evaluationKey)));
  }

  function componentRows(components = {}) {
    return Object.entries(components).map(([key, value]) => {
      const percentage = Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100)));
      return `<div class="evaluation-component"><span>${escapeHtml(key.replaceAll("_", " "))}</span><div class="bar"><i style="width:${percentage}%"></i></div><b>${percentage}%</b></div>`;
    }).join("") || '<p class="evaluation-empty">No score components.</p>';
  }

  function renderEvaluationDetail() {
    const container = document.querySelector("#evaluationDetail");
    const detail = phase9.selectedDetail;
    if (!detail) {
      document.querySelector("#evaluationDetailState").textContent = "Select a run";
      container.innerHTML = '<p class="evaluation-empty">Select an evaluation run.</p>';
      return;
    }
    document.querySelector("#evaluationDetailState").textContent = `${detail.status} · ${Math.round(Number(detail.score || 0) * 100)}%`;
    const findings = (detail.findings || []).map((finding) => `<article class="evaluation-finding ${safeClass(finding.severity)}"><strong>${escapeHtml(finding.code || finding.severity || "Finding")}</strong><small>${escapeHtml(finding.message || "")}${Array.isArray(finding.items) && finding.items.length ? `<br />${escapeHtml(finding.items.join(" · "))}` : ""}</small></article>`).join("") || '<p class="evaluation-empty">No findings.</p>';
    const evidence = (detail.evidence || []).map((item) => `<article class="evaluation-evidence-item"><strong>${escapeHtml(item.type)} · ${escapeHtml(item.title)}</strong><small>Strength ${Math.round(Number(item.strength || 0) * 100)}% · ${escapeHtml(item.locator || item.content_hash.slice(0, 16))}</small></article>`).join("") || '<p class="evaluation-empty">No evidence records.</p>';
    const task = detail.task || {};
    const score = Math.max(0, Math.min(100, Math.round(Number(detail.score || 0) * 100)));
    container.innerHTML = `
      <div class="evaluation-profile-head"><div><h3>${escapeHtml(task.title || detail.task_key)}</h3><p>${escapeHtml(detail.recommendation.replaceAll("_", " "))}<br />${escapeHtml(task.target_identity || "Unknown agent")} · ${escapeHtml(task.target_runtime_key || "Unknown runtime")}</p></div><div class="evaluation-score-ring" style="--score:${score}%"><strong>${score}%</strong></div></div>
      <div class="evaluation-meta">
        <div><span>Status</span><strong>${escapeHtml(detail.status)}</strong></div>
        <div><span>Source status</span><strong>${escapeHtml(detail.source_status)}</strong></div>
        <div><span>Evidence</span><strong>${detail.evidence_count} supporting</strong></div>
        <div><span>Dispatch</span><strong>${escapeHtml(detail.source_dispatch_key || "No provenance")}</strong></div>
        <div><span>Policy</span><strong>${escapeHtml(detail.policy_key)}</strong></div>
        <div><span>Evaluator</span><strong>${escapeHtml(detail.evaluator_identity)}</strong></div>
        <div><span>Task</span><strong>${escapeHtml(detail.task_key)}</strong></div>
        <div><span>Evaluated</span><strong>${escapeHtml(formatDateTime(detail.created_at))}</strong></div>
      </div>
      <section class="evaluation-section"><h4>Score components</h4><div class="evaluation-components">${componentRows(detail.components)}</div></section>
      <section class="evaluation-section"><h4>Findings</h4><div class="evaluation-findings">${findings}</div></section>
      <section class="evaluation-section"><h4>Evidence chain</h4><div class="evaluation-evidence">${evidence}</div></section>
      <div class="evaluation-actions"><button class="secondary" id="evaluationRunAgain">Evaluate again</button><button class="primary" id="evaluationReplayTask">Replay task</button></div>
    `;
    container.querySelector("#evaluationRunAgain")?.addEventListener("click", () => evaluateAgain(detail.task_key));
    container.querySelector("#evaluationReplayTask")?.addEventListener("click", () => openReplayDialog(detail.task_key));
  }

  function renderReplays() {
    const container = document.querySelector("#evaluationReplayList");
    document.querySelector("#evaluationReplayCount").textContent = `${phase9.replays.length} replay runs`;
    if (!phase9.replays.length) {
      container.innerHTML = '<p class="evaluation-empty">No replay history for the current mission.</p>';
      return;
    }
    container.innerHTML = phase9.replays.map((replay) => {
      const comparison = replay.comparison || {};
      const delta = comparison.score_delta;
      const comparisonText = delta === null || delta === undefined
        ? "Comparison pending"
        : `${delta >= 0 ? "+" : ""}${Math.round(Number(delta) * 100)} points · ${comparison.improved ? "improved" : "not improved"}`;
      return `<article class="evaluation-replay-card"><header><div><strong>${escapeHtml(replay.source_task_key)} → ${escapeHtml(replay.replay_task_key)}</strong><small>${escapeHtml(replay.mode)} · ${escapeHtml(replay.key)}</small></div><span class="evaluation-status ${safeClass(replay.status)}">${escapeHtml(replay.status)}</span></header><p>${escapeHtml(replay.reason)}<br />${escapeHtml(comparisonText)}</p></article>`;
    }).join("");
  }

  async function selectEvaluation(key) {
    phase9.selected = phase9.evaluations.find((item) => item.key === key) || null;
    renderEvaluationList();
    if (!phase9.selected) return;
    try {
      phase9.selectedDetail = await operatorApi(`/api/evaluation/runs/${encodeURIComponent(key)}`, {}, true);
      renderEvaluationDetail();
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function loadEvaluation(silent = true) {
    try {
      const currentMission = missionKey();
      const query = currentMission ? `?mission_key=${encodeURIComponent(currentMission)}` : "";
      const [status, evaluations, replays] = await Promise.all([
        operatorApi("/api/evaluation/status", {}, true),
        operatorApi(`/api/evaluation/runs${query}`, {}, true),
        operatorApi(`/api/evaluation/replays${query}`, {}, true),
      ]);
      phase9.status = status;
      phase9.evaluations = evaluations;
      phase9.replays = replays;
      phase9.lastMissionKey = currentMission;
      if (phase9.selected && !evaluations.some((item) => item.key === phase9.selected.key)) {
        phase9.selected = null;
        phase9.selectedDetail = null;
      }
      renderStats();
      renderEvaluationList();
      renderEvaluationDetail();
      renderReplays();
    } catch (error) {
      document.querySelector("#evaluationState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function runEvaluationTick() {
    try {
      const result = await operatorApi("/api/evaluation/tick", { method: "POST" });
      showMessage(`Evaluator processed ${result.evaluated} tasks: ${result.passed} pass, ${result.warned} warn, ${result.failed} fail.`, "success");
      await loadEvaluation(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function evaluateAgain(taskKey) {
    try {
      const detail = await operatorApi(`/api/evaluation/tasks/${encodeURIComponent(taskKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true, note: "Manual verification run from the Command Center." }),
      });
      showMessage(`${taskKey} re-evaluated at ${Math.round(Number(detail.score || 0) * 100)}%.`, "success");
      await loadEvaluation(true);
      await selectEvaluation(detail.key);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function openReplayDialog(taskKey = "") {
    const currentMission = missionKey();
    if (!currentMission && !taskKey) {
      showMessage("Select a mission before creating a replay.", "error");
      return;
    }
    try {
      const query = currentMission ? `?mission_key=${encodeURIComponent(currentMission)}&limit=200` : "?limit=200";
      const tasks = await operatorApi(`/api/collaboration/tasks${query}`, {}, true);
      const eligible = tasks.filter((task) => ["COMPLETED", "REVIEW", "FAILED", "BLOCKED", "CANCELLED"].includes(task.status));
      if (!eligible.length) {
        showMessage("No completed, reviewed, blocked or failed task is available for replay.", "error");
        return;
      }
      const source = document.querySelector("#replaySourceTask");
      source.innerHTML = eligible.map((task) => `<option value="${escapeHtml(task.key)}">${escapeHtml(task.key)} · ${escapeHtml(task.title)} · ${escapeHtml(task.status)}</option>`).join("");
      if (taskKey && eligible.some((task) => task.key === taskKey)) source.value = taskKey;
      const runtime = document.querySelector("#replayRuntime");
      runtime.innerHTML = '<option value="">Automatic / original</option>' + state.runtimes.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.name)}</option>`).join("");
      document.querySelector("#replayMode").value = "REROUTE";
      document.querySelector("#replayTargetIdentity").value = "";
      document.querySelector("#replayReason").value = "Re-run the work package to verify the conclusion and compare evidence quality against the original execution.";
      document.querySelector("#replayAutoDispatch").checked = true;
      document.querySelector("#evaluationReplayMessage").textContent = "REROUTE excludes the previous selected agent and runtime when possible.";
      document.querySelector("#evaluationReplayDialog").showModal();
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function createReplay(event) {
    event.preventDefault();
    const message = document.querySelector("#evaluationReplayMessage");
    message.textContent = "Creating controlled replay…";
    try {
      const replay = await operatorApi("/api/evaluation/replays", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_task_key: document.querySelector("#replaySourceTask").value,
          mode: document.querySelector("#replayMode").value,
          reason: document.querySelector("#replayReason").value.trim(),
          preferred_runtime_key: document.querySelector("#replayRuntime").value || null,
          target_identity: document.querySelector("#replayTargetIdentity").value.trim() || null,
          auto_dispatch: document.querySelector("#replayAutoDispatch").checked,
        }),
      });
      message.textContent = `${replay.key} created as ${replay.replay_task_key}.`;
      setTimeout(() => document.querySelector("#evaluationReplayDialog").close(), 700);
      showMessage(`${replay.key} queued for ${replay.mode.toLowerCase()} execution.`, "success");
      await loadEvaluation(true);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function startPolling() {
    if (phase9.timer) clearInterval(phase9.timer);
    phase9.timer = setInterval(() => {
      if (document.hidden) return;
      const currentMission = missionKey();
      void loadEvaluation(currentMission === phase9.lastMissionKey);
    }, 10000);
  }

  async function initialize() {
    if (phase9.initialized) return;
    phase9.initialized = true;
    installUi();
    startPolling();
    await loadEvaluation(false);
  }

  void initialize();
})();
