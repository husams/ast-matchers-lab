// Match results from `astmatcher/runQuery`: a table in the bottom panel, a
// bindings outline in the Explorer, and highlights in the sample file.
//
// Both views show the result *by bind id*, from the server's `bindings`: one
// group per `.bind("id")` listing each distinct AST node once, with the matches
// that bound it. The server tells nodes apart by AST address, so the `d` of
// `cxxRecordDecl(eachOf(...)).bind("d")` is one record found by matches #1 and
// #2, while `v` is two fields. clang-query's implicit `root` binding is hidden
// unless nothing else is bound, or "Show root" is on.
//
// The result shape is documented in astmatcher-lsp/astmatcher_lsp/run.py.

const crypto = require("crypto");
const vscode = require("vscode");
const { isRecordBinding, detailForBinding } = require("./binding-detail");

/**
 * [{ id, nodes: [{ key, b, sels: [{q,m,b}], matches: ["1", "2"] }] }] — one
 * node per distinct AST node; `root` first.
 */
function groupByBind(result, showRoot) {
  if (!result || !result.bindings) return [];
  const multi = result.queries.length > 1;
  const ids = Object.keys(result.bindings);
  const onlyRoot = ids.every((id) => id === "root");
  return ids.filter((id) => id !== "root" || showRoot || onlyRoot).map((id) => ({
    id,
    nodes: result.bindings[id].map((n, i) => ({
      key: `${id}:${n.node || i}`,
      b: { ...n, id },
      detail: detailForBinding(n),
      record: isRecordBinding(n),
      sels: n.matches.map((m) => ({ q: m.query, m: m.match, b: m.binding })),
      matches: n.matches.map((m) => (multi ? `${m.query + 1}.${m.index}` : String(m.index))),
    })),
  }));
}

/** Holds the last result; everything else listens to it. */
class ResultStore {
  constructor() {
    this.result = undefined;
    this.running = false;
    this.showRoot = false;
    this.selected = undefined;          // { q, m, b } node selector or { id } group selector
    this.generation = 0;               // changes whenever selectors may refer to new results
    this.emitter = new vscode.EventEmitter();
    this.onDidChange = this.emitter.event;
  }

  set(result) {
    this.generation++;
    this.result = result;
    this.running = false;
    this.selected = undefined;
    this.emitter.fire("result");
  }

  setRunning(info) {
    this.generation++;
    this.result = undefined;
    this.running = info;
    this.selected = undefined;
    this.emitter.fire("running");
  }

  setCancellable(cancellable) {
    if (!this.running) return;
    this.running = { ...this.running, cancellable };
    this.emitter.fire("running");
  }

  requestCancellation(progress = {}) {
    if (!this.running) return;
    this.running = { ...this.running, cancelRequested: true,
      completedFiles: progress.completedFiles ?? this.running.completedFiles,
      totalFiles: progress.totalFiles ?? this.running.totalFiles };
    this.emitter.fire("running");
  }

  cancelRequestFailed() {
    if (!this.running) return;
    this.running = { ...this.running, cancelRequested: false };
    this.emitter.fire("running");
  }

  finishCancelled() {
    const current = this.result || { queries: [], bindings: {}, files: [], errors: [],
      sample: this.running && this.running.sample };
    this.result = { ...current, ok: false, cancelled: true,
      completedFiles: this.running && this.running.completedFiles,
      totalFiles: this.running && this.running.totalFiles };
    this.running = false;
    this.selected = undefined;
    this.generation++;
    this.emitter.fire("result");
  }

  startStreaming(progress) {
    this.generation++;
    this.result = {
      ok: false, sample: progress.sample, flags: progress.flags || [],
      target: progress.target, queries: [], bindings: {}, files: [], errors: [],
      stderr: "", durationMs: 0, truncated: false,
      cache: { enabled: !!progress.cache?.enabled, hits: 0, misses: 0,
               location: progress.cache?.location || null },
    };
    this.running = { ...this.running, completedFiles: 0,
                     totalFiles: progress.totalFiles };
    this.emitter.fire("result");
  }

  appendStreamingFile(progress) {
    const result = this.result;
    if (!result || !this.running || result.files.includes(progress.file)) return;
    const offset = result.queries.length;
    result.queries.push(...(progress.queries || []));
    for (const [id, nodes] of Object.entries(progress.bindings || {})) {
      const existing = result.bindings[id] ||= [];
      for (const node of nodes) existing.push({ ...node,
        matches: node.matches.map((m) => ({ ...m, query: m.query + offset })) });
    }
    result.files.push(progress.file);
    result.errors.push(...(progress.errors || []));
    result.stderr += progress.stderr || "";
    result.cache.hits += progress.cache?.hits || 0;
    result.cache.misses += progress.cache?.misses || 0;
    result.durationMs = progress.durationMs || result.durationMs;
    this.running = { ...this.running, completedFiles: progress.completedFiles,
                     totalFiles: progress.totalFiles, currentFile: progress.file };
    this.emitter.fire("result");
  }

  toggleRoot() {
    this.showRoot = !this.showRoot;
    vscode.commands.executeCommand("setContext", "astmatcher.showRoot", this.showRoot);
    this.emitter.fire("result");
  }

  select(sel) {
    this.selected = sel;
    this.emitter.fire("selection");
  }

  groups() {
    return groupByBind(this.result, this.showRoot);
  }

  binding(sel) {
    const q = this.result && this.result.queries[sel.q];
    const m = q && q.matches[sel.m];
    return m && m.bindings[sel.b];
  }

  match(sel) {
    const q = this.result && this.result.queries[sel.q];
    return q && q.matches[sel.m];
  }
}

function toRange(r) {
  return new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character);
}

function formatLocation(b) {
  return b && b.range ? `${b.range.start.line + 1}:${b.range.start.character + 1}` : "";
}

// ------------------------------------------------------------------ highlight

class Highlighter {
  constructor(store) {
    this.store = store;
    // The selected node(s) only; editor selections carry the source text.
    this.current = vscode.window.createTextEditorDecorationType({
      backgroundColor: new vscode.ThemeColor("editor.findMatchBackground"),
      borderColor: new vscode.ThemeColor("editor.findMatchBorder"),
      borderStyle: "solid",
      borderWidth: "1px",
      overviewRulerColor: new vscode.ThemeColor("editorOverviewRuler.findMatchForeground"),
      overviewRulerLane: vscode.OverviewRulerLane.Full,
      after: { color: new vscode.ThemeColor("editorInfo.foreground"), margin: "0 0 0 2px",
               fontWeight: "bold" },
    });
    this.subscriptions = [
      this.current,
      store.onDidChange(() => this.refresh()),
      vscode.window.onDidChangeVisibleTextEditors(() => this.refresh()),
    ];
  }

  refresh() {
    for (const editor of vscode.window.visibleTextEditors) this.paint(editor);
  }

  paint(editor) {
    const file = editor.document.uri.fsPath;
    const current = [];
    const label = (b) => ({ after: { contentText: `‹${b.id}›` } });
    const sel = this.store.selected;
    const nodes = sel && sel.id
      ? nodesForBinding(this.store, sel)
      : [sel && this.store.binding(sel)].filter(Boolean);
    for (const b of uniqueLocatedNodes(nodes)) {
      if (!b.range || b.file !== file) continue;
      current.push({ range: toRange(b.range), hoverMessage: `**${b.id}** — \`${b.kind}\``,
                     renderOptions: label(b) });
    }
    editor.setDecorations(this.current, current);
  }

  dispose() {
    this.subscriptions.forEach((s) => s.dispose());
  }
}

function rangeKey(file, range) {
  return `${file}:${range.start.line}:${range.start.character}:${range.end.line}:${range.end.character}`;
}

function uniqueLocatedNodes(nodes) {
  const seen = new Set();
  return nodes.filter((b) => {
    if (!b.file || !b.range) return false;
    const key = rangeKey(b.file, b.range);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function nodesForBinding(store, sel) {
  const group = store.groups().find((g) => g.id === sel.id);
  return (group ? group.nodes : []).filter((n) => !sel.file || n.b.file === sel.file)
    .map((n) => n.b);
}

/** Open the selected node or binding group and select its exact source range(s). */
async function reveal(store, sel) {
  if (!sel || sel.generation !== store.generation) {
    vscode.window.showInformationMessage("AST Matcher: this result is stale; run the query again.");
    return;
  }
  const group = sel && sel.id;
  const nodes = group
    ? nodesForBinding(store, sel)
    : [store.binding(sel)].filter(Boolean);
  if (!nodes.length) return;
  store.select(sel);
  const located = uniqueLocatedNodes(nodes);
  if (!located.length) {
    const b = nodes[0];
    vscode.window.setStatusBarMessage(`astmatcher: "${b.id}" (${b.kind}) has no source location`, 4000);
    return;
  }
  const byFile = new Map();
  for (const b of located) {
    if (!byFile.has(b.file)) byFile.set(b.file, []);
    byFile.get(b.file).push(toRange(b.range));
  }
  let active;
  for (const [file, ranges] of byFile) {
    const visible = vscode.window.visibleTextEditors.find((e) => e.document.uri.fsPath === file);
    const editor = await vscode.window.showTextDocument(vscode.Uri.file(file), {
      viewColumn: visible ? visible.viewColumn : vscode.ViewColumn.Active,
      preserveFocus: file !== located[0].file, preview: false,
    });
    editor.selections = ranges.map((r) => new vscode.Selection(r.start, r.end));
    editor.revealRange(editor.selections[0], vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    if (file === located[0].file) active = editor;
  }
  if (active && byFile.size > 1) await vscode.window.showTextDocument(active.document.uri, {
    viewColumn: active.viewColumn, preserveFocus: false, preview: false,
  });
}

// ------------------------------------------------------------------ tree

/** Outline: source file -> binding id -> distinct AST nodes. */
class BindingsTree {
  constructor(store) {
    this.store = store;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
    store.onDidChange((why) => { if (why !== "selection") this.emitter.fire(); });
  }

  getChildren(node) {
    const result = this.store.result;
    if (!result) return [];
    if (!node) {
      const byFile = new Map();
      for (const g of this.store.groups()) for (const n of g.nodes) {
        const file = n.b.file || result.sample || "(unknown source)";
        if (!byFile.has(file)) byFile.set(file, new Map());
        const groups = byFile.get(file);
        if (!groups.has(g.id)) groups.set(g.id, { id: g.id, nodes: [] });
        groups.get(g.id).nodes.push(n);
      }
      return [...byFile].sort(([a], [b]) => a.localeCompare(b))
        .map(([file, groups]) => ({ type: "file", file,
          groups: [...groups.values()], generation: this.store.generation }));
    }
    if (node.generation !== this.store.generation) return [];
    if (node.type === "file") return node.groups.map((group) => ({
      type: "bind", group, file: node.file, generation: node.generation,
    }));
    if (node.type === "bind") {
      return node.group.nodes.map((n) => ({ type: "node", node: n,
        file: node.file, generation: node.generation }));
    }
    return [];
  }

  getTreeItem(node) {
    const C = vscode.TreeItemCollapsibleState;
    if (node.type === "file") {
      const name = require("path").basename(node.file);
      const item = new vscode.TreeItem(name, C.Expanded);
      item.id = `file:${node.file}`;
      item.description = node.file;
      item.tooltip = node.file;
      item.iconPath = new vscode.ThemeIcon("file", new vscode.ThemeColor("symbolIcon-fileForeground"));
      return item;
    }
    if (node.type === "bind") {
      const n = node.group.nodes.length;
      const item = new vscode.TreeItem(node.group.id, C.Expanded);
      item.id = `bind:${node.file || ""}:${node.group.id}`;
      item.description = `${n} node${n === 1 ? "" : "s"}`;
      item.iconPath = new vscode.ThemeIcon(node.group.id === "root" ? "symbol-class"
                                                                     : "symbol-field");
      item.command = { command: "astmatcher.revealBinding", title: "Select binding",
                       arguments: [{ id: node.group.id, ...(node.file ? { file: node.file } : {}),
                         generation: node.generation }] };
      return item;
    }
    const { b, matches, sels } = node.node;
    const detail = detailForBinding(b);
    const item = new vscode.TreeItem(`${b.kind}${detail ? " · " + detail : ""}`, C.None);
    const location = formatLocation(b);
    item.description = `#${matches.join(", #")}` + (location ? ` · ${location}` : "");
    item.tooltip = new vscode.MarkdownString()
      .appendMarkdown(`**${b.id}** — \`${b.kind}\` — match #${matches.join(", #")}\n\n`)
      .appendCodeblock(b.text || b.summary || "", "cpp")
      .appendMarkdown(location ? `\n${location}` : "\n_no source location_");
    item.iconPath = new vscode.ThemeIcon("symbol-misc");
    item.command = { command: "astmatcher.revealBinding", title: "Reveal",
      arguments: [{ ...sels[0], ...(node.file ? { file: node.file } : {}),
        generation: node.generation }] };
    if (isRecordBinding(b)) item.contextValue = "astmatcherRecordBinding";
    return item;
  }
}

// ------------------------------------------------------------------ table

class MatchesView {
  constructor(context, store, handlers) {
    this.context = context;
    this.store = store;
    this.handlers = handlers;
    this.view = undefined;
    this.pendingMode = "results";
    this.lastProgressPostAt = 0;
    this.pendingProgressTimer = undefined;
    store.onDidChange((why) => this.post(why));
  }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((msg) => {
      if (msg.type === "reveal") this.handlers.reveal({ ...msg.sel,
        generation: msg.generation });
      else if (msg.type === "explore-record") this.handlers.exploreRecord({
        sel: msg.sel, generation: msg.generation,
      });
      else if (msg.type === "command") vscode.commands.executeCommand(msg.command);
      else if (msg.type === "settings-open") this.showSettings();
      else if (msg.type === "settings-load") this.loadSettings();
      else if (msg.type === "settings-save") this.saveSettings(msg.values);
      else if (msg.type === "target-select") {
        vscode.commands.executeCommand("astmatcher.selectTarget").then((settings) => {
          if (settings && this.view) this.view.webview.postMessage({ type: "target-selected", settings });
        });
      }
      else if (msg.type === "settings-cancel") {
        this.pendingMode = "results";
        this.post("result");
      }
      else if (msg.type === "open") vscode.window.showTextDocument(vscode.Uri.file(msg.file));
      else if (msg.type === "ready") {
        if (this.pendingMode === "settings") this.loadSettings();
        else {
          this.post("result");
          vscode.commands.executeCommand("astmatcher.getRunSettings").then((settings) => {
            if (this.view) this.view.webview.postMessage({ type: "settings-data", settings });
          });
        }
      }
    });
    view.onDidChangeVisibility(() => {
      if (view.visible && this.pendingMode !== "settings") this.post("result");
    });
  }

  /** Bring the panel up without taking focus from the editor. */
  show() {
    this.pendingMode = "results";
    if (this.view) this.view.show(true);
    else vscode.commands.executeCommand("astmatcher.matches.focus")
      .then(() => vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup"));
  }

  showSettings() {
    this.pendingMode = "settings";
    if (this.view) {
      this.view.show(true);
      this.loadSettings();
    } else vscode.commands.executeCommand("astmatcher.matches.focus")
      .then(() => { if (this.view) this.loadSettings(); });
  }

  async loadSettings() {
    this.pendingMode = "settings";
    try {
      const settings = await vscode.commands.executeCommand("astmatcher.getRunSettings");
      if (this.view) this.view.webview.postMessage({ type: "settings", settings });
    } catch (error) {
      if (this.view) this.view.webview.postMessage({ type: "settings-error",
        message: error.message || String(error) });
    }
  }

  async saveSettings(values) {
    try {
      const settings = await vscode.commands.executeCommand("astmatcher.saveRunSettings", values);
      this.pendingMode = "results";
      if (this.view) this.view.webview.postMessage({ type: "settings-saved", settings });
    } catch (error) {
      if (this.view) this.view.webview.postMessage({ type: "settings-error",
        message: error.message || String(error) });
    }
  }

  post(why) {
    if (!this.view) return;
    if (why === "result" && this.store.running) {
      const elapsed = Date.now() - this.lastProgressPostAt;
      if (elapsed < 100) {
        if (!this.pendingProgressTimer) this.pendingProgressTimer = setTimeout(() => {
          this.pendingProgressTimer = undefined;
          this.post("result");
        }, 100 - elapsed);
        return;
      }
      this.lastProgressPostAt = Date.now();
    } else if (this.pendingProgressTimer) {
      clearTimeout(this.pendingProgressTimer);
      this.pendingProgressTimer = undefined;
    }
    this.view.webview.postMessage({
      type: why === "selection" ? "selection" : "state",
      result: this.store.result, running: this.store.running, selected: this.store.selected,
      groups: this.store.groups(), showRoot: this.store.showRoot,
      generation: this.store.generation,
    });
  }

  html(webview) {
    const nonce = crypto.randomBytes(16).toString("base64");
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "media", "matches.js"));
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, "media", "matches.css"));
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${styleUri}">
<title>AST Matches</title>
</head>
<body>
<header id="bar">
  <div id="results-toolbar">
    <span id="summary">Run a query with ⌘↵ to see its matches here.</span>
    <span class="spacer"></span>
    <input id="filter" type="search" placeholder="Filter" aria-label="Filter matches">
    <label class="toggle" title="Also list clang-query's implicit root binding">
      <input id="show-root" type="checkbox"> Show root</label>
    <button id="sample" title="Choose the file the query runs against">Sample…</button>
    <button id="settings" title="Run scope, compiler, results and cache settings">Settings</button>
    <div class="scope-menu" role="group" aria-label="Run scope">
      <button id="run-file" title="Run against one source file">File</button>
      <button id="run-directory" title="Run against a directory">Directory</button>
      <button id="run-workspace" title="Run against the workspace">Workspace</button>
    </div>
    <button id="cancel-query" title="Cancel the running query" hidden>Cancel Query</button>
    <button id="rerun" title="Run the query again">Run</button>
  </div>
  <div id="settings-toolbar" hidden>
    <strong>Run settings</strong><span class="spacer"></span>
    <button id="settings-cancel">Back</button>
    <button id="settings-save">Save settings</button>
  </div>
</header>
<main id="results-screen">
<div id="cache-info" role="status" hidden></div>
<div id="no-results" role="status" hidden>No matching bindings were found for this run.</div>
<table id="table" hidden>
  <thead><tr id="head"></tr></thead>
  <tbody id="rows"></tbody>
</table>
</main>
<main id="settings-screen" hidden>
  <form id="settings-form">
    <fieldset><legend>Run scope</legend>
      <label>Scope <select name="scope" id="scope">
        <option value="file">File</option><option value="directory">Directory</option>
        <option value="workspace">Workspace</option></select></label>
      <label>Target path <span class="path-control"><input id="target-path" name="targetPath" type="text">
        <button type="button" id="select-target">Browse…</button></span></label>
    </fieldset>
    <fieldset><legend>Compiler</legend>
      <label>Compiler flags <span class="hint">Enter one compiler argument per line.</span>
        <textarea name="flags" id="flags" rows="3" spellcheck="false"></textarea></label>
      <label>compile_commands.json <input name="compileCommands" id="compile-commands" type="text"></label>
      <label>Traversal <select name="traversal" id="traversal">
        <option value="AsIs">AsIs</option>
        <option value="IgnoreUnlessSpelledInSource">IgnoreUnlessSpelledInSource</option>
      </select></label>
      <label>Excluded paths <span class="hint">One glob per line.</span>
        <textarea name="exclusions" id="exclusions" rows="3" spellcheck="false"
          placeholder="One glob per line"></textarea></label>
    </fieldset>
    <fieldset><legend>Results</legend><div id="columns" role="group" aria-label="Visible result columns"></div></fieldset>
    <fieldset><legend>Cache</legend>
      <label><input name="cacheEnabled" id="cache-enabled" type="checkbox"> Enable result cache</label>
      <label>Cache location <input name="cacheLocation" id="cache-location" type="text"></label>
    </fieldset>
    <div id="settings-error" role="alert" hidden></div>
  </form>
</main>
<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

module.exports = { ResultStore, Highlighter, BindingsTree, MatchesView, reveal, toRange,
                   groupByBind, formatLocation };
