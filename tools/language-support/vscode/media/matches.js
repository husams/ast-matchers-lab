// AST Matches webview: file -> binding id -> distinct AST nodes.
(function () {
  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);
  const COLUMNS = [
    { key: "match", title: "Binding", cls: "tree", value: (n) => n.sels[0].q * 1e6 + n.sels[0].m,
      html: (n, last) => `<span class="branch">${last ? "└─" : "├─"}</span> #${esc(n.matches.join(", #"))}` },
    { key: "kind", title: "AST kind", cls: "kind", value: (n) => n.b.kind,
      html: (n) => esc(n.b.kind) },
    { key: "semanticKind", title: "Declaration kind", cls: "kind",
      value: (n) => n.b.semanticKind || "", html: (n) => esc(n.b.semanticKind || "—") },
    { key: "detail", title: "Entity", cls: "detail", value: (n) => n.detail || n.b.summary || "",
      html: (n) => `<span class="entity-detail">${esc(n.detail || n.b.summary || "—")}</span>` +
        (n.record ? '<button type="button" class="explore-record" title="Explore this record and its relationships">Explore Record</button>' : "") +
        (n.b.text ? `<details class="source-details"><summary>Source</summary><pre><code>${esc(n.b.text)}</code></pre></details>` : "") },
    { key: "summary", title: "Summary", cls: "summary", value: (n) => n.b.summary,
      html: (n) => esc(n.b.summary) },
    { key: "text", title: "Source", cls: "src", value: (n) => n.b.text,
      html: (n) => esc(n.b.text) },
    { key: "location", title: "Location", cls: "loc",
      value: (n) => n.b.range ? n.b.range.start.line * 1e6 + n.b.range.start.character : Number.MAX_SAFE_INTEGER,
      html: (n) => n.b.range ? `${n.b.range.start.line + 1}:${n.b.range.start.character + 1}` : '<span class="muted">—</span>' },
  ];
  const DEFAULT_COLUMNS = ["match", "kind", "semanticKind", "detail", "location"];
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const key = (sel) => sel ? `${sel.q}:${sel.m}:${sel.b}` : "";
  let state = { result: undefined, running: false, selected: undefined, groups: [] };
  let settings = {};
  let draftTargetPath = "";
  let filter = "";
  let sort = { key: "", dir: 1 };
  const collapsedFiles = new Set();
  const collapsedBindings = new Set();

  function columns() {
    const visible = Array.isArray(settings.visibleColumns) ? settings.visibleColumns : DEFAULT_COLUMNS;
    const selected = COLUMNS.filter((c) => visible.includes(c.key));
    return selected.length ? selected : [COLUMNS[0]];
  }

  function groupedFiles() {
    const byFile = new Map();
    for (const g of state.groups || []) for (const n of g.nodes) {
      const file = n.b.file || (state.result && state.result.sample) || "(unknown source)";
      if (!byFile.has(file)) byFile.set(file, new Map());
      const binds = byFile.get(file);
      if (!binds.has(g.id)) binds.set(g.id, { id: g.id, nodes: [] });
      binds.get(g.id).nodes.push(n);
    }
    for (const query of (state.result && state.result.queries) || []) {
      const file = query.translationUnit;
      if (file && (query.count > 0 || query.matches?.length) && !byFile.has(file))
        byFile.set(file, new Map());
    }
    return [...byFile].sort(([a], [b]) => a.localeCompare(b)).map(([file, binds]) => ({
      file, groups: [...binds.values()].sort((a, b) => a.id.localeCompare(b.id)),
    }));
  }

  function setScreen(screen) {
    const settingsOn = screen === "settings";
    $("settings-screen").hidden = !settingsOn;
    $("results-screen").hidden = settingsOn;
    $("results-toolbar").hidden = settingsOn;
    $("settings-toolbar").hidden = !settingsOn;
    if (settingsOn) $("scope").focus();
  }

  function renderSummary() {
    const r = state.result;
    const s = $("summary");
    if (state.running) {
      const done = state.running.completedFiles || 0;
      const total = state.running.totalFiles;
      const matches = (r?.queries || []).reduce((n, q) => n + q.count, 0);
      const progressText = total == null ? "Scanning files…" :
        `Scanning ${done}/${total} files · ${matches} match${matches === 1 ? "" : "es"}`;
      s.textContent = total == null
        ? `Running against ${state.running.sample || "selected scope"}…`
        : `${matches} match${matches === 1 ? "" : "es"} · ${done}/${total} files scanned · ${state.running.sample}`;
      $("cache-info").hidden = false;
      $("cache-info").textContent = progressText;
      return;
    }
    if (!r) { s.textContent = "Run a query with ⌘↵ to see its matches here."; return; }
    const total = (r.queries || []).reduce((n, q) => n + q.count, 0);
    const base = (r.sample || "").split(/[\\/]/).pop() || "selected files";
    const cache = r.cache || r.cacheMetadata || {};
    const hit = cache.hits > 0 || cache.hit === true || r.cacheHit === true || cache.status === "hit";
    const cacheText = cache.enabled === false ? "cache off" : (hit ? "cache hit" : "cache miss");
    s.innerHTML = `<b>${total}</b> match${total === 1 ? "" : "es"} across ` +
      `<span class="file-name">${esc(base)}</span> ` +
      `<span class="muted">${esc((r.flags || []).join(" "))} · ${esc(r.durationMs)} ms · ${cacheText}` +
      `${r.truncated ? " · truncated" : ""}</span>`;
    const info = $("cache-info");
    const cacheMeta = r.cacheMetadata || r.cache;
    info.hidden = !cacheMeta;
    info.textContent = !cacheMeta ? "" : cache.enabled === false ? "Cache off" :
      `${hit ? "Cache hit" : "Cache miss"}` +
      `${Number.isFinite(cache.hits) ? ` · ${cache.hits} hit${cache.hits === 1 ? "" : "s"}` : ""}` +
      `${Number.isFinite(cache.misses) ? ` · ${cache.misses} miss${cache.misses === 1 ? "" : "es"}` : ""}` +
      `${cache.location ? ` · ${cache.location}` : ""}` +
      `${Array.isArray(cache.warnings) && cache.warnings.length ? ` · ${cache.warnings.join("; ")}` : ""}`;
  }

  function visibleNodes(group) {
    const needle = filter.toLowerCase();
    let nodes = group.nodes.filter((n) => !needle ||
      `${group.id} ${n.b.kind} ${n.b.semanticKind} ${n.detail} ${n.b.summary} ${n.b.text} ${n.b.location} ${n.b.file}`
        .toLowerCase().includes(needle));
    const activeColumns = columns();
    if (sort.key) {
      const col = activeColumns.find((c) => c.key === sort.key) || COLUMNS.find((c) => c.key === sort.key);
      nodes = nodes.map((n, i) => [n, i]).sort(([a, i], [b, j]) => {
        const x = col.value(a), y = col.value(b);
        const cmp = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
        return cmp * sort.dir || i - j;
      }).map(([n]) => n);
    }
    return nodes;
  }

  function render() {
    renderSummary();
    const table = $("table");
    const r = state.result;
    if (!r) { table.hidden = true; $("no-results").hidden = true; return; }
    const totalMatches = (r.queries || []).reduce((n, q) => n + q.count, 0);
    const noResults = $("no-results");
    noResults.hidden = !!state.running || totalMatches > 0;
    const activeColumns = columns();
    $("head").innerHTML = activeColumns.map((c) => {
      const arrow = sort.key === c.key ? (sort.dir > 0 ? " ▲" : " ▼") : "";
      return `<th class="${c.cls}" data-key="${c.key}" tabindex="0" scope="col" title="Sort by ${c.title}">${c.title}${arrow}</th>`;
    }).join("");
    $("show-root").checked = !!state.showRoot;
    const html = [];
    const files = groupedFiles();
    files.forEach(({ file, groups }) => {
      let visibleGroups = groups.map((g) => ({ ...g, nodes: visibleNodes(g) })).filter((g) => g.nodes.length);
      if (filter && !file.toLowerCase().includes(filter.toLowerCase()) && !visibleGroups.length) return;
      const fileOpen = !collapsedFiles.has(file) || !!filter;
      const total = visibleGroups.reduce((n, g) => n + g.nodes.length, 0);
      html.push(`<tr class="file-group" tabindex="0" data-file="${esc(file)}" aria-expanded="${fileOpen}">` +
        `<td colspan="${activeColumns.length}"><span class="twisty">${fileOpen ? "▾" : "▸"}</span> ` +
        `<span class="file-name" title="${esc(file)}">${esc(file.split(/[\\/]/).pop())}</span> ` +
        `<span class="file-path">${esc(file)}</span><span class="muted"> · ${total} node${total === 1 ? "" : "s"}</span></td></tr>`);
      if (!fileOpen) return;
      visibleGroups.forEach((g) => {
        const groupKey = `${file}\n${g.id}`;
        const groupOpen = !collapsedBindings.has(groupKey) || !!filter;
        html.push(`<tr class="group" tabindex="0" data-group="${esc(g.id)}" data-file="${esc(file)}" ` +
          `aria-expanded="${groupOpen}"><td colspan="${activeColumns.length}">` +
          `<span class="twisty">${groupOpen ? "▾" : "▸"}</span> ` +
          `<span class="${g.id === "root" ? "id-root" : "id"}">${esc(g.id)}</span> ` +
          `<span class="muted">— ${g.nodes.length} node${g.nodes.length === 1 ? "" : "s"}</span></td></tr>`);
        if (!groupOpen) return;
        g.nodes.forEach((n, i) => {
          const s = n.sels[0];
          const last = i === g.nodes.length - 1;
          html.push(`<tr class="binding" tabindex="0" data-keys="${esc(n.sels.map(key).join(" "))}" ` +
            `data-q="${s.q}" data-m="${s.m}" data-b="${s.b}" data-file="${esc(file)}">` +
            activeColumns.map((c) => {
              const tip = c.key === "summary" ? n.b.summary : c.key === "text" ? n.b.text : "";
              return `<td class="${c.cls}"${tip ? ` title="${esc(tip)}"` : ""}>${c.html(n, last)}</td>`;
            }).join("") + "</tr>");
        });
      });
    });
    $("rows").innerHTML = html.join("") || `<tr><td class="empty" colspan="${Math.max(1, activeColumns.length)}">No matches.</td></tr>`;
    table.hidden = totalMatches === 0;
    mark();
  }

  function mark() {
    const sel = key(state.selected);
    for (const tr of document.querySelectorAll("tr.group")) {
      tr.classList.toggle("selected", !!state.selected && state.selected.id === tr.dataset.group &&
        (!state.selected.file || state.selected.file === tr.dataset.file));
    }
    for (const tr of document.querySelectorAll("tr.binding")) {
      tr.classList.toggle("selected", !!sel && tr.dataset.keys.split(" ").includes(sel));
    }
  }

  function activate(tr) {
    if (tr) vscode.postMessage({ type: "reveal", sel: {
      q: +tr.dataset.q, m: +tr.dataset.m, b: +tr.dataset.b,
    }, generation: state.generation });
  }
  function activateGroup(tr) {
    if (tr) vscode.postMessage({ type: "reveal", generation: state.generation,
      sel: { id: tr.dataset.group, file: tr.dataset.file } });
  }
  function toggle(tr, set, value, selector) {
    if (set.has(value)) set.delete(value); else set.add(value);
    render();
    const fileTarget = tr.classList.contains("file-group");
    const again = [...document.querySelectorAll(selector)].find((row) =>
      row.dataset.file === tr.dataset.file && (fileTarget
        ? row.classList.contains("file-group") : row.dataset.group === tr.dataset.group));
    if (again) again.focus();
  }

  $("rows").addEventListener("click", (e) => {
    const explore = e.target.closest("button.explore-record");
    if (explore) {
      const row = explore.closest("tr.binding");
      if (row) vscode.postMessage({ type: "explore-record", generation: state.generation, sel: {
        q: +row.dataset.q, m: +row.dataset.m, b: +row.dataset.b,
      } });
      return;
    }
    if (e.target.closest("details.source-details")) return;
    const file = e.target.closest("tr.file-group");
    const group = e.target.closest("tr.group");
    if (file && e.target.closest(".twisty")) toggle(file, collapsedFiles, file.dataset.file, "tr.file-group");
    else if (file) vscode.postMessage({ type: "open", file: file.dataset.file });
    else if (group && e.target.closest(".twisty")) toggle(group, collapsedBindings,
      `${group.dataset.file}\n${group.dataset.group}`, "tr.group");
    else if (group) activateGroup(group);
    else activate(e.target.closest("tr.binding"));
  });
  $("rows").addEventListener("keydown", (e) => {
    if (e.target.closest("button.explore-record, details.source-details")) return;
    const row = e.target.closest("tr.file-group, tr.group, tr.binding");
    if (!row) return;
    const isFile = row.classList.contains("file-group");
    const isGroup = row.classList.contains("group");
    if ((isFile || isGroup) && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      const open = row.getAttribute("aria-expanded") === "true";
      if (e.key === "ArrowLeft" && open || e.key === "ArrowRight" && !open) {
        e.preventDefault();
        const set = isFile ? collapsedFiles : collapsedBindings;
        const keyValue = isFile ? row.dataset.file : `${row.dataset.file}\n${row.dataset.group}`;
        toggle(row, set, keyValue, isFile ? "tr.file-group" : "tr.group");
      }
      return;
    }
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (row.classList.contains("file-group")) vscode.postMessage({ type: "open", file: row.dataset.file });
      else if (row.classList.contains("group")) activateGroup(row);
      else activate(row);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const all = [...document.querySelectorAll("tr.file-group, tr.group, tr.binding")];
      const next = all[all.indexOf(row) + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) next.focus();
    }
  });
  $("filter").addEventListener("input", (e) => { filter = e.target.value; render(); });
  $("head").addEventListener("click", (e) => {
    const th = e.target.closest("th"); if (!th) return;
    sortBy(th.dataset.key);
  });
  $("head").addEventListener("keydown", (e) => {
    const th = e.target.closest("th");
    if (th && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); sortBy(th.dataset.key); }
  });
  function sortBy(keyValue) {
    if (sort.key !== keyValue) sort = { key: keyValue, dir: 1 };
    else if (sort.dir > 0) sort.dir = -1; else sort = { key: "", dir: 1 };
    render();
  }
  $("show-root").addEventListener("change", () => vscode.postMessage({ type: "command", command: "astmatcher.toggleRoot" }));
  $("sample").addEventListener("click", () => vscode.postMessage({ type: "command", command: "astmatcher.selectSample" }));
  $("rerun").addEventListener("click", () => vscode.postMessage({ type: "command", command: "astmatcher.runQuery" }));
  $("settings").addEventListener("click", () => vscode.postMessage({ type: "settings-open" }));
  $("run-file").addEventListener("click", () => vscode.postMessage({ type: "command", command: "astmatcher.runFile" }));
  $("run-directory").addEventListener("click", () => vscode.postMessage({ type: "command", command: "astmatcher.runDirectory" }));
  $("run-workspace").addEventListener("click", () => vscode.postMessage({ type: "command", command: "astmatcher.runWorkspace" }));
  $("settings-cancel").addEventListener("click", () => vscode.postMessage({ type: "settings-cancel" }));
  $("settings-save").addEventListener("click", saveSettings);
  $("select-target").addEventListener("click", () => vscode.postMessage({ type: "target-select" }));
  $("columns").addEventListener("change", () => {
    if (!document.querySelector('input[name="visibleColumns"]:checked')) {
      const minimum = document.querySelector('input[name="visibleColumns"][value="match"]');
      if (minimum) minimum.checked = true;
    }
  });
  $("scope").addEventListener("change", () => updateTargetState());
  $("cache-enabled").addEventListener("change", () => { $("cache-location").disabled = !$("cache-enabled").checked; });

  function updateTargetState() {
    const scope = $("scope").value;
    const target = $("target-path");
    if (scope === "workspace") {
      if (!target.disabled) draftTargetPath = target.value;
      target.value = "All workspace folders";
      target.disabled = true;
      $("select-target").disabled = true;
    } else {
      if (target.disabled || target.value === "All workspace folders") target.value = draftTargetPath;
      else draftTargetPath = target.value;
      target.disabled = false;
      $("select-target").disabled = false;
    }
  }
  function renderSettings(value) {
    settings = value || {};
    $("scope").value = settings.scope || "file";
    draftTargetPath = settings.targetPath || "";
    $("target-path").value = draftTargetPath;
    updateTargetState();
    $("flags").value = Array.isArray(settings.flags) ? settings.flags.join("\n") : (settings.flags || "");
    $("compile-commands").value = settings.compileCommands || "";
    $("traversal").value = settings.traversal || "AsIs";
    $("exclusions").value = Array.isArray(settings.exclusions) ? settings.exclusions.join("\n") : "";
    $("cache-enabled").checked = !!settings.cacheEnabled;
    $("cache-location").value = settings.cacheLocation || "";
    $("cache-location").disabled = !settings.cacheEnabled;
    const selected = Array.isArray(settings.visibleColumns) ? settings.visibleColumns : DEFAULT_COLUMNS;
    $("columns").innerHTML = COLUMNS.map((c) => `<label class="column-choice"><input type="checkbox" name="visibleColumns" value="${c.key}" ${selected.includes(c.key) ? "checked" : ""}> ${c.title}</label>`).join("");
    $("settings-error").hidden = true;
    setScreen("settings");
  }
  function saveSettings(e) {
    e.preventDefault();
    const values = {
      visibleColumns: [...document.querySelectorAll('input[name="visibleColumns"]:checked')].map((el) => el.value),
      flags: $("flags").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
      compileCommands: $("compile-commands").value.trim(),
      traversal: $("traversal").value,
      exclusions: $("exclusions").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
      cacheEnabled: $("cache-enabled").checked,
      cacheLocation: $("cache-location").value.trim(),
      scope: $("scope").value,
      targetPath: $("scope").value === "workspace" ? "" : $("target-path").value.trim(),
    };
    vscode.postMessage({ type: "settings-save", values });
  }

  window.addEventListener("message", (e) => {
    const msg = e.data;
    if (msg.type === "selection") { state.selected = msg.selected; mark(); return; }
    if (msg.type === "settings-data") { settings = msg.settings || {}; render(); return; }
    if (msg.type === "settings") { renderSettings(msg.settings); return; }
    if (msg.type === "target-selected") {
      if (msg.settings) {
        settings = { ...settings, scope: msg.settings.scope, targetPath: msg.settings.targetPath };
        $("scope").value = settings.scope || "file";
        draftTargetPath = settings.targetPath || draftTargetPath;
        $("target-path").value = draftTargetPath;
        updateTargetState();
      }
      return;
    }
    if (msg.type === "settings-saved") { settings = msg.settings || settings; setScreen("results"); render(); return; }
    if (msg.type === "settings-error") {
      $("settings-error").textContent = msg.message || "Settings could not be saved.";
      $("settings-error").hidden = false;
      setScreen("settings");
      return;
    }
    state = msg;
    setScreen("results");
    render();
  });
  vscode.postMessage({ type: "ready" });
})();
