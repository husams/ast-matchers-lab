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
    this.emitter = new vscode.EventEmitter();
    this.onDidChange = this.emitter.event;
  }

  set(result) {
    this.result = result;
    this.running = false;
    this.selected = undefined;
    this.emitter.fire("result");
  }

  setRunning(info) {
    this.running = info;
    this.emitter.fire("running");
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
      ? (this.store.groups().find((g) => g.id === sel.id) || { nodes: [] }).nodes.map((n) => n.b)
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

/** Open the selected node or binding group and select its exact source range(s). */
async function reveal(store, sel) {
  const group = sel && sel.id;
  const nodes = group
    ? (store.groups().find((g) => g.id === sel.id) || { nodes: [] }).nodes.map((n) => n.b)
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

/** Outline: bind id -> the distinct nodes it bound. */
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
      const errs = result.errors.map((e, i) => ({ type: "error", error: e, i }));
      return [...errs, ...this.store.groups().map((g) => ({ type: "bind", group: g }))];
    }
    if (node.type === "bind") {
      return node.group.nodes.map((n) => ({ type: "node", node: n }));
    }
    return [];
  }

  getTreeItem(node) {
    const C = vscode.TreeItemCollapsibleState;
    if (node.type === "error") {
      const item = new vscode.TreeItem(node.error.message, C.None);
      item.iconPath = new vscode.ThemeIcon("error", new vscode.ThemeColor("errorForeground"));
      return item;
    }
    if (node.type === "bind") {
      const n = node.group.nodes.length;
      const item = new vscode.TreeItem(node.group.id, C.Expanded);
      item.id = `bind:${node.group.id}`;
      item.description = `${n} node${n === 1 ? "" : "s"}`;
      item.iconPath = new vscode.ThemeIcon(node.group.id === "root" ? "symbol-class"
                                                                     : "symbol-field");
      item.command = { command: "astmatcher.revealBinding", title: "Select binding",
                       arguments: [{ id: node.group.id }] };
      return item;
    }
    const { b, matches, sels } = node.node;
    const item = new vscode.TreeItem(`${b.kind}${b.summary ? " " + b.summary : ""}`, C.None);
    item.description = `#${matches.join(", #")}` + (b.location ? ` · ${b.location}` : "");
    item.tooltip = new vscode.MarkdownString()
      .appendMarkdown(`**${b.id}** — \`${b.kind}\` — match #${matches.join(", #")}\n\n`)
      .appendCodeblock(b.text || b.summary || "", "cpp")
      .appendMarkdown(b.location ? `\n${b.location}` : "\n_no source location_");
    item.iconPath = new vscode.ThemeIcon("symbol-misc");
    item.command = { command: "astmatcher.revealBinding", title: "Reveal", arguments: [sels[0]] };
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
    store.onDidChange((why) => this.post(why));
  }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((msg) => {
      if (msg.type === "reveal") this.handlers.reveal(msg.sel);
      else if (msg.type === "command") vscode.commands.executeCommand(msg.command);
      else if (msg.type === "open") vscode.window.showTextDocument(vscode.Uri.file(msg.file));
      else if (msg.type === "ready") this.post("result");
    });
    view.onDidChangeVisibility(() => { if (view.visible) this.post("result"); });
  }

  /** Bring the panel up without taking focus from the editor. */
  show() {
    if (this.view) this.view.show(true);
    else vscode.commands.executeCommand("astmatcher.matches.focus")
      .then(() => vscode.commands.executeCommand("workbench.action.focusActiveEditorGroup"));
  }

  post(why) {
    if (!this.view) return;
    this.view.webview.postMessage({
      type: why === "selection" ? "selection" : "state",
      result: this.store.result, running: this.store.running, selected: this.store.selected,
      groups: this.store.groups(), showRoot: this.store.showRoot,
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
  <span id="summary">Run a query with ⌘↵ to see its matches here.</span>
  <span class="spacer"></span>
  <input id="filter" type="search" placeholder="Filter" aria-label="Filter matches">
  <label class="toggle" title="Also list clang-query's implicit root binding">
    <input id="show-root" type="checkbox"> Show root</label>
  <button id="sample" title="Choose the file the query runs against">Sample…</button>
  <button id="rerun" title="Run the query again">Run</button>
</header>
<section id="errors" hidden></section>
<table id="table" hidden>
  <thead><tr id="head"></tr></thead>
  <tbody id="rows"></tbody>
</table>
<pre id="stderr" hidden></pre>
<script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

module.exports = { ResultStore, Highlighter, BindingsTree, MatchesView, reveal, toRange,
                   groupByBind };
