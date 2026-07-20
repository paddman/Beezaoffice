(() => {
  const phase10 = {
    status: null,
    templates: [],
    selectedTemplate: null,
    selectedVersionKey: null,
    selectedRun: null,
    initialized: false,
    timer: null,
  };

  function installUi() {
    if (document.querySelector("#sopBuilder")) return;

    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.id = "sopNav";
    nav.innerHTML = 'SOP Builder <span id="sopNavCount">0</span>';
    document.querySelector("#evaluationNav")?.after(nav);

    const panel = document.createElement("section");
    panel.className = "panel sop-panel";
    panel.id = "sopBuilder";
    panel.innerHTML = `
      <div class="panel-title">
        <div><p class="eyebrow">PHASE 10 · SOP BUILDER & WORKFLOW TEMPLATES</p><h2>Versioned Operating Procedures</h2></div>
        <div class="sop-header-state"><span id="sopState">Starting</span><b id="sopCount">0</b></div>
      </div>
      <p class="dispatch-intro">Turn verified work into repeatable operating procedures. Published versions create governed missions, route tasks, stop at approval gates, wait for evidence verification and execute rollback tasks when a later step fails.</p>
      <div class="sop-toolbar">
        <span id="sopWorkerSummary">Loading SOP worker…</span>
        <div class="sop-toolbar-actions"><button class="secondary" id="sopTick">Run worker</button><button class="secondary" id="sopDerive">Derive selected mission</button><button class="primary" id="sopNew">+ New SOP</button></div>
      </div>
      <div id="sopStats" class="sop-stats"></div>
      <div class="sop-layout">
        <section class="sop-box">
          <div class="sop-box-head"><div><strong>SOP library</strong><small>Published procedures and editable drafts</small></div><span id="sopLibraryState" class="sop-status">0 templates</span></div>
          <div id="sopTemplateList" class="sop-template-list"></div>
        </section>
        <section class="sop-box">
          <div class="sop-box-head"><div><strong id="sopDetailTitle">Procedure detail</strong><small id="sopDetailSubtitle">Version graph, runs, approvals and rollback</small></div><div id="sopDetailActions" class="sop-actions"></div></div>
          <div id="sopDetail" class="sop-detail"><p class="sop-empty">Select an SOP template.</p></div>
        </section>
      </div>
      <p id="sopMessage" class="sop-message"></p>
    `;
    document.querySelector("#evaluationCenter")?.after(panel);

    const templateDialog = document.createElement("dialog");
    templateDialog.id = "sopTemplateDialog";
    templateDialog.innerHTML = `
      <form method="dialog" id="sopTemplateForm">
        <div class="dialog-head"><div><p class="eyebrow">VERSIONED PROCEDURE</p><h2>Create SOP Draft</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="sop-form-grid">
          <label>Template key<input id="sopTemplateKey" required minlength="3" pattern="[a-z][a-z0-9._-]*" placeholder="capacity-review" /></label>
          <label>Category<input id="sopTemplateCategory" value="Operations" required /></label>
          <label class="full">Name<input id="sopTemplateName" required minlength="3" placeholder="Verified Capacity Review" /></label>
          <label class="full">Description<textarea id="sopTemplateDescription" placeholder="What outcome this procedure produces and when it should be used."></textarea></label>
          <label class="full">Input schema JSON<textarea id="sopInputSchema" class="sop-code-editor"></textarea></label>
          <label class="full">Workflow definition JSON<textarea id="sopDefinition" class="sop-code-editor" required></textarea></label>
          <label class="full">Changelog<input id="sopChangelog" value="Initial draft" required /></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create draft</button></div>
        <p id="sopTemplateFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(templateDialog);

    const versionDialog = document.createElement("dialog");
    versionDialog.id = "sopVersionDialog";
    versionDialog.innerHTML = `
      <form method="dialog" id="sopVersionForm">
        <div class="dialog-head"><div><p class="eyebrow">IMMUTABLE VERSIONING</p><h2>Create New Draft Version</h2></div><button value="cancel" class="icon-button">×</button></div>
        <label>Changelog<input id="sopVersionChangelog" required minlength="3" placeholder="Add independent verification and rollback" /></label>
        <label>Workflow definition JSON<textarea id="sopVersionDefinition" class="sop-code-editor" required></textarea></label>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create version</button></div>
        <p id="sopVersionFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(versionDialog);

    const runDialog = document.createElement("dialog");
    runDialog.id = "sopRunDialog";
    runDialog.innerHTML = `
      <form method="dialog" id="sopRunForm">
        <div class="dialog-head"><div><p class="eyebrow">GOVERNED EXECUTION</p><h2>Start SOP Run</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="sop-form-grid">
          <label class="full">Mission title<input id="sopRunMissionTitle" placeholder="Optional custom mission title" /></label>
          <label>Priority<select id="sopRunPriority"><option>NORMAL</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select></label>
          <label>Commander<input id="sopRunCommander" value="Beeza Commander" required /></label>
        </div>
        <div class="sop-section"><header><h4>Procedure inputs</h4><span id="sopRunVersionLabel"></span></header><div id="sopRunInputs" class="sop-input-fields"></div></div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Create governed mission</button></div>
        <p id="sopRunFormMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(runDialog);

    const deriveDialog = document.createElement("dialog");
    deriveDialog.id = "sopDeriveDialog";
    deriveDialog.innerHTML = `
      <form method="dialog" id="sopDeriveForm">
        <div class="dialog-head"><div><p class="eyebrow">VERIFIED WORK → SOP</p><h2>Derive Draft from Mission</h2></div><button value="cancel" class="icon-button">×</button></div>
        <div class="sop-form-grid">
          <label>Template key<input id="sopDeriveKey" required minlength="3" pattern="[a-z][a-z0-9._-]*" /></label>
          <label>Category<input id="sopDeriveCategory" value="Derived" required /></label>
          <label class="full">Name<input id="sopDeriveName" required minlength="3" /></label>
          <label class="full">Description<textarea id="sopDeriveDescription"></textarea></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button type="submit" value="default" class="primary">Derive PASS-verified tasks</button></div>
        <p id="sopDeriveMessage" class="form-message"></p>
      </form>
    `;
    document.body.append(deriveDialog);

    nav.addEventListener("click", () => panel.scrollIntoView({ behavior: "smooth", block: "start" }));
    panel.querySelector("#sopTick").addEventListener("click", runWorkerTick);
    panel.querySelector("#sopNew").addEventListener("click", openTemplateDialog);
    panel.querySelector("#sopDerive").addEventListener("click", openDeriveDialog);
    templateDialog.querySelector("#sopTemplateForm").addEventListener("submit", createTemplate);
    versionDialog.querySelector("#sopVersionForm").addEventListener("submit", createVersion);
    runDialog.querySelector("#sopRunForm").addEventListener("submit", createRun);
    deriveDialog.querySelector("#sopDeriveForm").addEventListener("submit", deriveTemplate);
  }

  function showMessage(message, type = "") {
    const node = document.querySelector("#sopMessage");
    if (!node) return;
    node.textContent = message;
    node.className = `sop-message ${type}`;
  }

  function parseJson(text, fallback = {}) {
    const value = String(text || "").trim();
    if (!value) return fallback;
    return JSON.parse(value);
  }

  function selectedVersion() {
    const versions = phase10.selectedTemplate?.versions || [];
    return versions.find((item) => item.key === phase10.selectedVersionKey)
      || versions.find((item) => item.status === "PUBLISHED")
      || versions[0]
      || null;
  }

  function renderStats() {
    const stats = phase10.status?.stats || {};
    const statuses = stats.run_statuses || {};
    const cards = [
      ["Templates", stats.templates || 0, `${stats.published_templates || 0} published`],
      ["Versions", stats.versions || 0, "Immutable definitions"],
      ["Active runs", stats.active_runs || 0, `${statuses.WAITING_APPROVAL || 0} awaiting approval`],
      ["Completed", stats.completed_runs || 0, "Successful SOP missions"],
      ["Failed", stats.failed_runs || 0, `${statuses.ROLLING_BACK || 0} rolling back`],
      ["All runs", stats.runs || 0, "Execution history"],
    ];
    document.querySelector("#sopStats").innerHTML = cards.map(([label, value, detail]) => `<article class="sop-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
    document.querySelector("#sopCount").textContent = String(stats.templates || 0);
    document.querySelector("#sopNavCount").textContent = String((statuses.WAITING_APPROVAL || 0) + (statuses.ROLLING_BACK || 0));
    const worker = phase10.status?.worker || {};
    document.querySelector("#sopState").textContent = worker.status || "starting";
    document.querySelector("#sopWorkerSummary").textContent = `${worker.status || "starting"} · ${worker.interval_seconds || 3}s · processed ${worker.last_processed || 0} · completed ${worker.last_completed || 0} · failed ${worker.last_failed || 0}${worker.last_error ? ` · ${worker.last_error}` : ""}`;
  }

  function renderTemplateList() {
    const container = document.querySelector("#sopTemplateList");
    document.querySelector("#sopLibraryState").textContent = `${phase10.templates.length} templates`;
    if (!phase10.templates.length) {
      container.innerHTML = '<p class="sop-empty">No SOP templates.</p>';
      return;
    }
    container.innerHTML = phase10.templates.map((template) => {
      const version = template.published_version;
      const nodes = version?.definition?.nodes?.length || 0;
      return `
        <button class="sop-template-card ${phase10.selectedTemplate?.key === template.key ? "active" : ""}" data-sop-template="${escapeHtml(template.key)}">
          <header><div><strong>${escapeHtml(template.name)}</strong><small>${escapeHtml(template.key)} · ${escapeHtml(template.category)}</small></div><span class="sop-status ${safeClass(template.status)}">${escapeHtml(template.status)}</span></header>
          <p>${escapeHtml(template.description || "No description")}</p>
          <footer><span>v${template.current_version} · ${nodes} nodes</span><span>${template.run_count || 0} runs</span></footer>
        </button>
      `;
    }).join("");
    container.querySelectorAll("[data-sop-template]").forEach((button) => button.addEventListener("click", () => selectTemplate(button.dataset.sopTemplate)));
  }

  function renderActions() {
    const container = document.querySelector("#sopDetailActions");
    const template = phase10.selectedTemplate;
    if (!template) {
      container.innerHTML = "";
      return;
    }
    const version = selectedVersion();
    const actions = [
      '<button class="primary" data-sop-action="run">Run SOP</button>',
      '<button class="secondary" data-sop-action="version">New version</button>',
    ];
    if (version?.status === "DRAFT") actions.push('<button class="secondary" data-sop-action="publish">Publish draft</button>');
    container.innerHTML = actions.join("");
    container.querySelectorAll("[data-sop-action]").forEach((button) => button.addEventListener("click", () => templateAction(button.dataset.sopAction)));
  }

  function renderFlow(version) {
    const nodes = version?.definition?.nodes || [];
    if (!nodes.length) return '<p class="sop-empty">Version has no nodes.</p>';
    return `<div class="sop-flow">${nodes.map((node, index) => `
      <article class="sop-flow-node">
        <header><strong>${index + 1}. ${escapeHtml(node.title)}</strong><span class="sop-status ${node.node_type === "APPROVAL" ? "waiting_approval" : "running"}">${escapeHtml(node.node_type)}</span></header>
        <small>${escapeHtml(node.key)}${node.depends_on?.length ? ` · after ${escapeHtml(node.depends_on.join(", "))}` : " · start node"}</small>
        <p>${escapeHtml(node.objective || "Approval gate")}</p>
        <footer>
          <span class="sop-chip">${escapeHtml(node.routing_mode || "AUTO")}</span>
          <span class="sop-chip">${escapeHtml(node.review_policy || "AUTO")} review</span>
          ${node.verification_required ? '<span class="sop-chip">verification required</span>' : ""}
          ${node.rollback ? '<span class="sop-chip">rollback defined</span>' : ""}
        </footer>
      </article>
    `).join("")}</div>`;
  }

  function renderRuns(template) {
    const runs = template.runs || [];
    if (!runs.length) return '<p class="sop-empty">No execution history.</p>';
    return `<div class="sop-run-list">${runs.map((run) => `
      <button class="sop-run-card ${phase10.selectedRun?.key === run.key ? "active" : ""}" data-sop-run="${escapeHtml(run.key)}">
        <header><div><strong>${escapeHtml(run.key)}</strong><small>${escapeHtml(run.mission_key)} · ${escapeHtml(formatDateTime(run.created_at))}</small></div><span class="sop-status ${safeClass(run.status)}">${escapeHtml(run.status)}</span></header>
        <p>${escapeHtml(run.current_node_key || run.failure_reason || "No active node")}</p>
      </button>
    `).join("")}</div>`;
  }

  function renderRunDetail(run) {
    if (!run) return "";
    const nodes = run.nodes || [];
    const normalNodes = nodes.filter((node) => node.node_type !== "ROLLBACK");
    const completed = normalNodes.filter((node) => ["COMPLETED", "SKIPPED"].includes(node.status)).length;
    const progress = Math.round(100 * completed / Math.max(1, normalNodes.length));
    return `
      <section class="sop-section">
        <header><h4>Selected run</h4><div class="sop-actions">${["PENDING", "RUNNING", "WAITING_APPROVAL", "ROLLING_BACK"].includes(run.status) ? `<button class="secondary" data-run-action="tick">Advance</button><button class="danger-button" data-run-action="cancel">Cancel</button>` : ""}</div></header>
        <div class="sop-profile-head"><div><h3>${escapeHtml(run.key)}</h3><p>${escapeHtml(run.mission_key)} · ${escapeHtml(run.version_key)}<br />${escapeHtml(run.failure_reason || "Governed workflow execution")}</p></div><span class="sop-status ${safeClass(run.status)}">${escapeHtml(run.status)}</span></div>
        <div class="sop-progress"><header><strong>Workflow progress</strong><span>${completed}/${normalNodes.length} nodes · ${progress}%</span></header><div class="bar"><i style="width:${progress}%"></i></div></div>
        <div class="sop-node-grid" style="margin-top:10px">${nodes.map((node) => {
          const summary = node.task?.result?.summary || node.output?.summary || node.error || node.input?.objective || "Waiting";
          return `<article class="sop-node-card ${safeClass(node.status)}"><header><div><strong>${escapeHtml(node.node_key)}</strong><small>${escapeHtml(node.node_type)}${node.task_key ? ` · ${escapeHtml(node.task_key)}` : ""}</small></div><span class="sop-status ${safeClass(node.status)}">${escapeHtml(node.status)}</span></header><p>${escapeHtml(summary)}</p><footer>${node.status === "WAITING_APPROVAL" ? `<button class="primary" data-node-decision="approve" data-node-key="${escapeHtml(node.node_key)}">Approve</button><button class="danger-button" data-node-decision="reject" data-node-key="${escapeHtml(node.node_key)}">Reject</button>` : ""}${node.task?.result?.verification ? `<span class="sop-chip">${escapeHtml(node.task.result.verification.status)} ${Math.round(Number(node.task.result.verification.score || 0) * 100)}%</span>` : ""}</footer></article>`;
        }).join("")}</div>
      </section>
    `;
  }

  function renderDetail() {
    const container = document.querySelector("#sopDetail");
    const template = phase10.selectedTemplate;
    renderActions();
    if (!template) {
      document.querySelector("#sopDetailTitle").textContent = "Procedure detail";
      container.innerHTML = '<p class="sop-empty">Select an SOP template.</p>';
      return;
    }
    const version = selectedVersion();
    document.querySelector("#sopDetailTitle").textContent = template.name;
    document.querySelector("#sopDetailSubtitle").textContent = `${template.category} · ${template.key}`;
    const versions = (template.versions || []).map((item) => `<button class="sop-version ${item.key === version?.key ? "active" : ""}" data-sop-version="${escapeHtml(item.key)}">v${item.version_number} · ${escapeHtml(item.status)}</button>`).join("");
    container.innerHTML = `
      <div class="sop-profile-head"><div><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.description || "No description")}</p></div><span class="sop-status ${safeClass(template.status)}">${escapeHtml(template.status)}</span></div>
      <div class="sop-meta">
        <div><span>Template</span><strong>${escapeHtml(template.key)}</strong></div>
        <div><span>Selected version</span><strong>${escapeHtml(version?.key || "none")}</strong></div>
        <div><span>Checksum</span><strong>${escapeHtml((version?.checksum || "").slice(0, 16) || "none")}</strong></div>
        <div><span>Owner</span><strong>${escapeHtml(template.owner_identity)}</strong></div>
      </div>
      <section class="sop-section"><header><h4>Versions</h4><span>Published versions are immutable</span></header><div class="sop-version-list">${versions}</div></section>
      <section class="sop-section"><header><h4>Workflow graph</h4><span>${version?.definition?.nodes?.length || 0} nodes</span></header>${renderFlow(version)}</section>
      <section class="sop-section"><header><h4>Execution history</h4><span>${template.runs?.length || 0} recent runs</span></header>${renderRuns(template)}</section>
      ${renderRunDetail(phase10.selectedRun)}
    `;
    container.querySelectorAll("[data-sop-version]").forEach((button) => button.addEventListener("click", () => {
      phase10.selectedVersionKey = button.dataset.sopVersion;
      renderDetail();
    }));
    container.querySelectorAll("[data-sop-run]").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.sopRun)));
    container.querySelectorAll("[data-run-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.runAction)));
    container.querySelectorAll("[data-node-decision]").forEach((button) => button.addEventListener("click", () => decideNode(button.dataset.nodeKey, button.dataset.nodeDecision)));
  }

  async function loadSop(silent = true) {
    try {
      const [status, templates] = await Promise.all([
        operatorApi("/api/sop/status", {}, true),
        operatorApi("/api/sop/templates", {}, true),
      ]);
      phase10.status = status;
      phase10.templates = templates;
      if (phase10.selectedTemplate) {
        const exists = templates.some((item) => item.key === phase10.selectedTemplate.key);
        if (exists) phase10.selectedTemplate = await operatorApi(`/api/sop/templates/${encodeURIComponent(phase10.selectedTemplate.key)}`, {}, true);
        else phase10.selectedTemplate = null;
      }
      if (phase10.selectedRun) {
        try {
          phase10.selectedRun = await operatorApi(`/api/sop/runs/${encodeURIComponent(phase10.selectedRun.key)}`, {}, true);
        } catch {
          phase10.selectedRun = null;
        }
      }
      renderStats();
      renderTemplateList();
      renderDetail();
    } catch (error) {
      document.querySelector("#sopState").textContent = "Access denied";
      if (!silent) showMessage(error.message, "error");
    }
  }

  async function selectTemplate(key) {
    phase10.selectedTemplate = await operatorApi(`/api/sop/templates/${encodeURIComponent(key)}`, {}, true);
    phase10.selectedVersionKey = phase10.selectedTemplate.versions?.find((item) => item.status === "PUBLISHED")?.key || phase10.selectedTemplate.versions?.[0]?.key || null;
    phase10.selectedRun = null;
    renderTemplateList();
    renderDetail();
  }

  async function selectRun(key) {
    phase10.selectedRun = await operatorApi(`/api/sop/runs/${encodeURIComponent(key)}`, {}, true);
    renderDetail();
  }

  function defaultDefinition() {
    return {
      rollback_on_failure: true,
      stop_on_failure: true,
      settings: {},
      nodes: [
        {
          key: "collect-evidence",
          title: "Collect evidence",
          node_type: "TASK",
          depends_on: [],
          objective: "Collect evidence for {{input.subject}} and identify source timestamps.",
          routing_mode: "AUTO",
          priority: "NORMAL",
          review_policy: "AUTO",
          required_skills: ["evidence"],
          required_capabilities: [],
          required_tools: [],
          required_clearance: "INTERNAL",
          expected_outputs: ["evidence summary"],
          acceptance_criteria: ["Sources are identified"],
          verification_required: true,
        },
        {
          key: "human-approval",
          title: "Approve execution",
          node_type: "APPROVAL",
          depends_on: ["collect-evidence"],
          objective: "Approve the evidence-backed execution plan.",
          routing_mode: "AUTO",
          priority: "HIGH",
          review_policy: "HUMAN",
          verification_required: false,
        },
        {
          key: "execute-and-verify",
          title: "Execute and verify",
          node_type: "TASK",
          depends_on: ["human-approval"],
          objective: "Execute the approved work for {{input.subject}}, preserve evidence and verify the result.",
          routing_mode: "AUTO",
          priority: "HIGH",
          review_policy: "AUTO",
          required_skills: [],
          required_capabilities: [],
          required_tools: [],
          required_clearance: "INTERNAL",
          expected_outputs: ["execution result", "verification evidence"],
          acceptance_criteria: ["Approved scope completed", "Result is verified"],
          verification_required: true,
          rollback: {
            title: "Rollback execution",
            objective: "Restore the previous known-good state for {{input.subject}} and preserve rollback evidence.",
            required_skills: [],
            required_tools: [],
            acceptance_criteria: ["Previous state restored"],
          },
        },
      ],
    };
  }

  function openTemplateDialog() {
    document.querySelector("#sopTemplateForm").reset();
    document.querySelector("#sopTemplateCategory").value = "Operations";
    document.querySelector("#sopInputSchema").value = JSON.stringify({ type: "object", required: ["subject"], properties: { subject: { type: "string" } } }, null, 2);
    document.querySelector("#sopDefinition").value = JSON.stringify(defaultDefinition(), null, 2);
    document.querySelector("#sopChangelog").value = "Initial draft";
    document.querySelector("#sopTemplateFormMessage").textContent = "Drafts must be published before execution.";
    document.querySelector("#sopTemplateDialog").showModal();
  }

  async function createTemplate(event) {
    event.preventDefault();
    const message = document.querySelector("#sopTemplateFormMessage");
    message.textContent = "Validating graph and creating draft…";
    try {
      const payload = {
        template_key: document.querySelector("#sopTemplateKey").value.trim(),
        name: document.querySelector("#sopTemplateName").value.trim(),
        description: document.querySelector("#sopTemplateDescription").value.trim(),
        category: document.querySelector("#sopTemplateCategory").value.trim(),
        input_schema: parseJson(document.querySelector("#sopInputSchema").value, {}),
        tags: [],
        definition: parseJson(document.querySelector("#sopDefinition").value),
        changelog: document.querySelector("#sopChangelog").value.trim(),
      };
      const created = await operatorApi("/api/sop/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      message.textContent = `${created.key} draft created.`;
      setTimeout(() => document.querySelector("#sopTemplateDialog").close(), 700);
      await loadSop(true);
      await selectTemplate(created.key);
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function openVersionDialog() {
    const version = selectedVersion();
    if (!phase10.selectedTemplate || !version) return;
    document.querySelector("#sopVersionChangelog").value = `Update from ${version.key}`;
    document.querySelector("#sopVersionDefinition").value = JSON.stringify(version.definition, null, 2);
    document.querySelector("#sopVersionFormMessage").textContent = "A new draft version is created; the published version remains executable.";
    document.querySelector("#sopVersionDialog").showModal();
  }

  async function createVersion(event) {
    event.preventDefault();
    const template = phase10.selectedTemplate;
    if (!template) return;
    const message = document.querySelector("#sopVersionFormMessage");
    message.textContent = "Validating new version…";
    try {
      const version = await operatorApi(`/api/sop/templates/${encodeURIComponent(template.key)}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          changelog: document.querySelector("#sopVersionChangelog").value.trim(),
          definition: parseJson(document.querySelector("#sopVersionDefinition").value),
        }),
      });
      message.textContent = `${version.key} created.`;
      setTimeout(() => document.querySelector("#sopVersionDialog").close(), 700);
      await selectTemplate(template.key);
      phase10.selectedVersionKey = version.key;
      renderDetail();
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function buildRunInputs(template) {
    const container = document.querySelector("#sopRunInputs");
    const schema = template.input_schema || {};
    const properties = schema.properties || {};
    const required = new Set(schema.required || []);
    const entries = Object.entries(properties);
    if (!entries.length) {
      container.innerHTML = '<p class="sop-empty full">This SOP has no declared inputs.</p>';
      return;
    }
    container.innerHTML = entries.map(([key, spec]) => {
      const type = String(spec.type || "string");
      const defaultValue = spec.default ?? "";
      if (type === "boolean") return `<label>${escapeHtml(key)}<select data-sop-input="${escapeHtml(key)}" data-input-type="boolean"><option value="true" ${defaultValue === true ? "selected" : ""}>true</option><option value="false" ${defaultValue === false ? "selected" : ""}>false</option></select></label>`;
      if (["integer", "number"].includes(type)) return `<label>${escapeHtml(key)}<input data-sop-input="${escapeHtml(key)}" data-input-type="${escapeHtml(type)}" type="number" value="${escapeHtml(defaultValue)}" ${required.has(key) ? "required" : ""} /></label>`;
      return `<label>${escapeHtml(key)}<input data-sop-input="${escapeHtml(key)}" data-input-type="string" value="${escapeHtml(defaultValue)}" ${required.has(key) ? "required" : ""} /></label>`;
    }).join("");
  }

  function openRunDialog() {
    const template = phase10.selectedTemplate;
    const version = selectedVersion();
    if (!template || !version || version.status !== "PUBLISHED") {
      showMessage("Select a published SOP version before running.", "error");
      return;
    }
    document.querySelector("#sopRunForm").reset();
    document.querySelector("#sopRunPriority").value = state.selectedMission?.priority || "NORMAL";
    document.querySelector("#sopRunCommander").value = "Beeza Commander";
    document.querySelector("#sopRunVersionLabel").textContent = `${template.key} · ${version.key}`;
    document.querySelector("#sopRunFormMessage").textContent = "Execution creates a new governed mission and uses the published immutable checksum.";
    buildRunInputs(template);
    document.querySelector("#sopRunDialog").showModal();
  }

  function collectRunInputs() {
    const values = {};
    document.querySelectorAll("#sopRunInputs [data-sop-input]").forEach((field) => {
      const key = field.dataset.sopInput;
      const type = field.dataset.inputType;
      if (type === "boolean") values[key] = field.value === "true";
      else if (type === "integer") values[key] = Number.parseInt(field.value, 10);
      else if (type === "number") values[key] = Number(field.value);
      else values[key] = field.value;
    });
    return values;
  }

  async function createRun(event) {
    event.preventDefault();
    const template = phase10.selectedTemplate;
    const version = selectedVersion();
    if (!template || !version) return;
    const message = document.querySelector("#sopRunFormMessage");
    message.textContent = "Creating governed SOP mission…";
    try {
      phase10.selectedRun = await operatorApi(`/api/sop/templates/${encodeURIComponent(template.key)}/runs?version_key=${encodeURIComponent(version.key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inputs: collectRunInputs(),
          mission_title: document.querySelector("#sopRunMissionTitle").value.trim() || null,
          mission_priority: document.querySelector("#sopRunPriority").value,
          commander: document.querySelector("#sopRunCommander").value.trim(),
        }),
      });
      message.textContent = `${phase10.selectedRun.key} created.`;
      setTimeout(() => document.querySelector("#sopRunDialog").close(), 700);
      await selectTemplate(template.key);
      await selectRun(phase10.selectedRun.key);
      showMessage(`${phase10.selectedRun.key} queued for SOP execution.`, "success");
    } catch (error) {
      message.textContent = error.message;
    }
  }

  async function publishVersion() {
    const template = phase10.selectedTemplate;
    const version = selectedVersion();
    if (!template || !version || version.status !== "DRAFT") return;
    if (!window.confirm(`Publish ${version.key}? Published definitions are immutable and replace the previous active version.`)) return;
    try {
      await operatorApi(`/api/sop/versions/${encodeURIComponent(version.key)}/publish`, { method: "POST" });
      showMessage(`${version.key} published.`, "success");
      await selectTemplate(template.key);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function templateAction(action) {
    if (action === "run") openRunDialog();
    else if (action === "version") openVersionDialog();
    else if (action === "publish") await publishVersion();
  }

  async function runAction(action) {
    const run = phase10.selectedRun;
    if (!run) return;
    try {
      if (action === "tick") {
        const response = await operatorApi(`/api/sop/runs/${encodeURIComponent(run.key)}/tick`, { method: "POST" });
        phase10.selectedRun = response.run;
        showMessage(`${run.key} advanced to ${response.run.status}.`, "success");
      } else if (action === "cancel") {
        if (!window.confirm(`Cancel ${run.key}? Already-dispatched remote work is not force-killed by SOP cancellation.`)) return;
        phase10.selectedRun = await operatorApi(`/api/sop/runs/${encodeURIComponent(run.key)}/cancel?note=${encodeURIComponent("Cancelled from SOP Builder")}`, { method: "POST" });
        showMessage(`${run.key} cancelled.`, "success");
      }
      await loadSop(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function decideNode(nodeKey, decision) {
    const run = phase10.selectedRun;
    if (!run) return;
    const note = window.prompt(`${decision === "approve" ? "Approval" : "Rejection"} note for ${nodeKey}:`, decision === "approve" ? "Evidence and risk reviewed; proceed." : "Rejected; revise the plan or evidence.");
    if (note === null) return;
    try {
      const response = await operatorApi(`/api/sop/runs/${encodeURIComponent(run.key)}/nodes/${encodeURIComponent(nodeKey)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note }),
      });
      phase10.selectedRun = response.run;
      showMessage(`${nodeKey} ${decision}d.`, decision === "approve" ? "success" : "error");
      await loadSop(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  async function runWorkerTick() {
    try {
      const result = await operatorApi("/api/sop/tick", { method: "POST" });
      showMessage(`SOP worker processed ${result.processed}: ${result.completed} completed, ${result.failed} failed, ${result.waiting} waiting.`, "success");
      await loadSop(true);
    } catch (error) {
      showMessage(error.message, "error");
    }
  }

  function slugify(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);
  }

  function openDeriveDialog() {
    const mission = state.selectedMission;
    if (!mission) {
      showMessage("Select a mission before deriving an SOP.", "error");
      return;
    }
    document.querySelector("#sopDeriveForm").reset();
    document.querySelector("#sopDeriveKey").value = `${slugify(mission.title)}-${Date.now().toString().slice(-4)}`;
    document.querySelector("#sopDeriveName").value = `${mission.title} SOP`;
    document.querySelector("#sopDeriveCategory").value = "Derived";
    document.querySelector("#sopDeriveDescription").value = `Derived from PASS-verified work in mission ${mission.key}.`;
    document.querySelector("#sopDeriveMessage").textContent = `Only PASS-verified Collaboration Tasks from ${mission.key} will be included.`;
    document.querySelector("#sopDeriveDialog").showModal();
  }

  async function deriveTemplate(event) {
    event.preventDefault();
    const mission = state.selectedMission;
    if (!mission) return;
    const message = document.querySelector("#sopDeriveMessage");
    message.textContent = "Reading verified task graph…";
    try {
      const created = await operatorApi(`/api/sop/derive/${encodeURIComponent(mission.key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_key: document.querySelector("#sopDeriveKey").value.trim(),
          name: document.querySelector("#sopDeriveName").value.trim(),
          description: document.querySelector("#sopDeriveDescription").value.trim(),
          category: document.querySelector("#sopDeriveCategory").value.trim(),
          tags: ["derived", "verified"],
        }),
      });
      message.textContent = `${created.key} derived from ${created.verified_tasks.length} verified tasks.`;
      setTimeout(() => document.querySelector("#sopDeriveDialog").close(), 750);
      await loadSop(true);
      await selectTemplate(created.key);
      showMessage(`${created.key} created as a draft. Review the graph, then publish.`, "success");
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function startPolling() {
    if (phase10.timer) clearInterval(phase10.timer);
    phase10.timer = setInterval(() => {
      if (!document.hidden) void loadSop(true);
    }, 7000);
  }

  async function initialize() {
    if (phase10.initialized) return;
    phase10.initialized = true;
    installUi();
    startPolling();
    await loadSop(false);
  }

  void initialize();
})();
