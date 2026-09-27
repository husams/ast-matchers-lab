// AST Matches panel: renders the runQuery result as a table, one row per
// binding, grouped by id. Rows select one node; group headers select all nodes.
(function () {
  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);
  let state = { result: undefined, running: false, selected: undefined };
  let filter = "";
  let sort = { key: "", dir: 1 };
  const collapsed = new Set();          // bind ids folded by the user

  // Rows are the distinct nodes of one bind group (see groupByBind in results.js).
  const COLUMNS = [
    // Tree column: the group row shows the bind id, its rows `├─ #1` / `└─ #2`.
    { key: "match", title: "Binding", cls: "tree", value: (n) => n.sels[0].q * 1e6 + n.sels[0].m,
      html: (n, last) => `<span class="branch">${last ? "└─" : "├─"}</span> ` +
        `#${esc(n.matches.join(", #"))}`,
      tip: (n) => `match #${n.matches.join(", #")}` },
    { key: "kind", title: "Kind", cls: "kind", value: (n) => n.b.kind, html: (n) => esc(n.b.kind) },
    { key: "summary", title: "Summary", cls: "summary", value: (n) => n.b.summary,
      html: (n) => esc(n.b.summary), tip: (n) => n.b.summary },
    { key: "text", title: "Source", cls: "src", value: (n) => n.b.text,
      html: (n) => esc(n.b.text), tip: (n) => n.b.text },
    { key: "location", title: "Location", cls: "loc",
      value: (n) => n.b.range
        ? `${n.b.file}:${String(n.b.range.start.line).padStart(8, "0")}:` +
          String(n.b.range.start.character).padStart(6, "0") : "~",
      html: (n) => n.b.location ? esc(n.b.location) : '<span class="muted">—</span>' },
  ];

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const key = (sel) => sel ? `${sel.q}:${sel.m}:${sel.b}` : "";

  function summary() {
    const r = state.result;
    const s = $("summary");
    if (state.running) {
      s.innerHTML = `Running against <b>${esc(state.running.sample)}</b>…`;
      return;
    }
    if (!r) {
      s.textContent = "Run a query with ⌘↵ to see its matches here.";
      return;
    }
    const total = r.queries.reduce((n, q) => n + q.count, 0);
    const base = r.sample.split(/[\\/]/).pop();
    s.innerHTML = `<b>${total}</b> match${total === 1 ? "" : "es"} in ` +
      `<a id="open-sample" title="${esc(r.sample)}">${esc(base)}</a> ` +
      `<span class="muted">${esc(r.flags.join(" "))} · ${r.durationMs} ms` +
      `${r.truncated ? " · truncated" : ""}</span>`;
    const link = $("open-sample");
    if (link) link.onclick = () => vscode.postMessage({ type: "open", file: r.sample });
  }

  function render() {
    summary();
    const r = state.result;
    const rows = $("rows");
    const errors = $("errors");
    const table = $("table");
    const stderr = $("stderr");
    rows.innerHTML = "";
    if (!r) {
      table.hidden = errors.hidden = stderr.hidden = true;
      return;
    }
    errors.hidden = !r.errors.length;
    errors.innerHTML = r.errors.map((e) => {
      const at = e.range ? `query line ${e.range.start.line + 1}: ` : "";
      return `<div>✖ ${esc(at + e.message)}</div>`;
    }).join("");
    stderr.hidden = !r.stderr;
    stderr.textContent = r.stderr || "";

    $("head").innerHTML = COLUMNS.map((c) => {
      const arrow = sort.key === c.key ? (sort.dir > 0 ? " ▲" : " ▼") : "";
      return `<th class="${c.cls || ""}" data-key="${c.key}" title="Sort by ${c.title}">` +
        `${c.title}${arrow}</th>`;
    }).join("");
    $("show-root").checked = !!state.showRoot;

    const needle = filter.toLowerCase();
    const html = [];
    for (const g of state.groups || []) {
      let nodes = g.nodes.filter((n) => !needle ||
        `${g.id} ${n.b.kind} ${n.b.summary} ${n.b.text} ${n.b.location}`.toLowerCase()
          .includes(needle));
      if (!nodes.length) continue;
      if (sort.key) {
        const col = COLUMNS.find((c) => c.key === sort.key);
        nodes = nodes.map((n, i) => [n, i]).sort(([a, i], [b, j]) => {
          const x = col.value(a), y = col.value(b);
          const cmp = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
          return cmp * sort.dir || i - j;
        }).map(([n]) => n);
      }
      const open = !collapsed.has(g.id) || !!needle;
      html.push(`<tr class="group" tabindex="0" data-group="${esc(g.id)}" ` +
        `aria-expanded="${open}"><td colspan="${COLUMNS.length}">` +
        `<span class="twisty">${open ? "▾" : "▸"}</span> ` +
        `<span class="${g.id === "root" ? "id-root" : "id"}">${esc(g.id)}</span> ` +
        `<span class="muted">— ${nodes.length} node${nodes.length === 1 ? "" : "s"}</span>` +
        `</td></tr>`);
      if (!open) continue;
      nodes.forEach((n, i) => {
        const s = n.sels[0];
        const last = i === nodes.length - 1;
        html.push(`<tr class="binding" tabindex="0" data-keys="${esc(n.sels.map(key).join(" "))}" ` +
          `data-q="${s.q}" data-m="${s.m}" data-b="${s.b}">` +
          COLUMNS.map((c) => `<td class="${c.cls || ""}"${c.tip ? ` title="${esc(c.tip(n))}"` : ""}>` +
            `${c.html(n, last)}</td>`).join("") + "</tr>");
      });
    }
    rows.innerHTML = html.join("") || `<tr><td class="empty" colspan="${COLUMNS.length}">` +
      `${r.queries.length ? "No matches." : ""}</td></tr>`;
    table.hidden = !r.queries.length;
    mark();
  }

  function mark() {
    const sel = key(state.selected);
    for (const tr of document.querySelectorAll("tr.group")) {
      tr.classList.toggle("selected", !!state.selected && state.selected.id === tr.dataset.group);
    }
    for (const tr of document.querySelectorAll("tr.binding")) {
      tr.classList.toggle("selected", !!sel && tr.dataset.keys.split(" ").includes(sel));
    }
  }

  function activate(tr) {
    if (!tr) return;
    vscode.postMessage({ type: "reveal",
      sel: { q: +tr.dataset.q, m: +tr.dataset.m, b: +tr.dataset.b } });
  }

  function activateGroup(tr) {
    if (tr) vscode.postMessage({ type: "reveal", sel: { id: tr.dataset.group } });
  }

  function toggle(tr) {
    const id = tr.dataset.group;
    if (collapsed.has(id)) collapsed.delete(id);
    else collapsed.add(id);
    render();
    const again = [...document.querySelectorAll("tr.group")].find((g) => g.dataset.group === id);
    if (again) again.focus();
  }

  $("rows").addEventListener("click", (e) => {
    const group = e.target.closest("tr.group");
    if (group && e.target.closest(".twisty")) toggle(group);
    else if (group) activateGroup(group);
    else activate(e.target.closest("tr.binding"));
  });
  $("rows").addEventListener("keydown", (e) => {
    const group = e.target.closest("tr.group");
    const expanded = group && group.getAttribute("aria-expanded") === "true";
    if (group && (e.key === "ArrowLeft" && expanded || e.key === "ArrowRight" && !expanded)) {
      e.preventDefault();
      toggle(group);
      return;
    }
    if (group && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      activateGroup(group);
      return;
    }
    const tr = e.target.closest("tr.binding, tr.group");
    if (!tr) return;
    if (tr.classList.contains("binding") && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      activate(tr);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const all = [...document.querySelectorAll("tr.binding, tr.group")];
      const next = all[all.indexOf(tr) + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) {
        next.focus();
        if (next.classList.contains("binding")) activate(next);
      }
    }
  });
  $("filter").addEventListener("input", (e) => { filter = e.target.value; render(); });
  $("head").addEventListener("click", (e) => {
    const th = e.target.closest("th");
    if (!th) return;
    // click: ascending, again: descending, third time: back to match order
    if (sort.key !== th.dataset.key) sort = { key: th.dataset.key, dir: 1 };
    else if (sort.dir > 0) sort.dir = -1;
    else sort = { key: "", dir: 1 };
    render();
  });
  $("show-root").addEventListener("change", () =>
    vscode.postMessage({ type: "command", command: "astmatcher.toggleRoot" }));
  $("sample").addEventListener("click", () =>
    vscode.postMessage({ type: "command", command: "astmatcher.selectSample" }));
  $("rerun").addEventListener("click", () =>
    vscode.postMessage({ type: "command", command: "astmatcher.runQuery" }));

  window.addEventListener("message", (e) => {
    const msg = e.data;
    if (msg.type === "selection") {
      state.selected = msg.selected;
      mark();
      return;
    }
    state = msg;
    render();
  });
  vscode.postMessage({ type: "ready" });
})();
