// VS Code client for the AST matcher DSL.
//
// The grammar and snippets work on their own; this file adds the language
// server (completion, hover, signature help, diagnostics, semantic tokens) and
// running the open .query file through clang-query: the server runs it
// (`astmatcher/runQuery`) and the matches land in the "AST Matches" panel, the
// "AST Match Bindings" tree and as highlights in the sample file.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");
const { Samples, SOURCE_EXTS } = require("./sample");
const { ResultStore, Highlighter, BindingsTree, MatchesView, reveal } = require("./results");

let client;
let terminal;
let samples;
let store;
let matchesView;
let statusItem;
let queryDiagnostics;
let lastQueryDoc;             // the .query document commands act on from the panel

const RELATIVE_SERVER = path.join(
  "tools", "language-support", "astmatcher-lsp", "bin", "astmatcher-lsp");

function config() {
  return vscode.workspace.getConfiguration("astmatcher");
}

/** Absolute path to the server launcher, or null when it cannot be found. */
function findServer() {
  const configured = config().get("server.path");
  if (configured) {
    const resolved = resolveWorkspace(configured);
    return fs.existsSync(resolved) ? resolved : null;
  }
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const candidate = path.join(folder.uri.fsPath, RELATIVE_SERVER);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function resolveWorkspace(value) {
  const folder = (vscode.workspace.workspaceFolders || [])[0];
  const root = folder ? folder.uri.fsPath : process.cwd();
  return path.isAbsolute(value) ? value : path.join(root, value.replace("${workspaceFolder}/", ""));
}

async function startServer(context) {
  if (!config().get("server.enabled")) {
    return;
  }
  const server = findServer();
  if (!server) {
    vscode.window.showWarningMessage(
      "astmatcher: language server not found — syntax highlighting only. " +
      "Set astmatcher.server.path to tools/language-support/astmatcher-lsp/bin/astmatcher-lsp.");
    return;
  }
  const python = config().get("server.python") || "python3";
  const serverOptions = {
    run: { command: server, args: ["--stdio"], transport: TransportKind.stdio,
           options: { env: { ...process.env, ASTMATCHER_PYTHON: python } } },
    debug: { command: server, args: ["--stdio"], transport: TransportKind.stdio,
             options: { env: { ...process.env, ASTMATCHER_PYTHON: python } } },
  };
  const clientOptions = {
    documentSelector: [
      { scheme: "file", language: "astmatcher" },
      { scheme: "untitled", language: "astmatcher" },
    ],
    outputChannelName: "AST Matcher DSL",
  };
  client = new LanguageClient("astmatcher", "AST Matcher DSL", serverOptions, clientOptions);
  context.subscriptions.push(client);
  await client.start();
}

function clangQuery() {
  const configured = config().get("clangQueryPath");
  if (configured) {
    return configured;
  }
  if (process.env.LLVM) {
    const candidate = path.join(process.env.LLVM, "bin", "clang-query");
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "clang-query";
}

/** The .query document a command should act on. */
function queryDocument() {
  const editor = vscode.window.activeTextEditor;
  if (editor && editor.document.languageId === "astmatcher") {
    return editor.document;
  }
  if (lastQueryDoc && !lastQueryDoc.isClosed) {
    return lastQueryDoc;
  }
  return undefined;
}

const QUERY_EXTS = new Set([".query", ".astmatcher"]);

/** Menus pass the clicked resource; run that query file if it is one. */
async function runQuery(arg) {
  const document = arg instanceof vscode.Uri && QUERY_EXTS.has(path.extname(arg.fsPath))
    ? await vscode.workspace.openTextDocument(arg)
    : queryDocument();
  if (!document) {
    vscode.window.showInformationMessage("astmatcher: open a .query file to run it.");
    return;
  }
  if (!client || !client.isRunning()) {
    return runQueryInTerminal();
  }
  const target = samples.resolve(document);
  if (!fs.existsSync(target.absolute)) {
    const choice = await vscode.window.showWarningMessage(
      `astmatcher: sample file not found: ${target.absolute}`, "Select Sample File…");
    if (choice) await selectSample();
    return;
  }
  store.setRunning({ sample: path.basename(target.absolute) });
  matchesView.show();
  let result;
  try {
    result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: "clang-query" },
      () => client.sendRequest("astmatcher/runQuery", {
        textDocument: { uri: document.uri.toString() },
        sample: target.absolute,
        flags: target.flags,
        clangQuery: clangQuery(),
        cwd: target.cwd,
      }));
  } catch (err) {
    store.set(undefined);
    vscode.window.showErrorMessage(`astmatcher: run failed: ${err.message || err}`);
    return;
  }
  store.set(result);
  queryDiagnostics.set(document.uri, result.errors.filter((e) => e.range).map((e) => {
    const r = e.range;
    const diag = new vscode.Diagnostic(
      new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character),
      e.message, vscode.DiagnosticSeverity.Error);
    diag.source = "clang-query";
    return diag;
  }));
  const total = result.queries.reduce((n, q) => n + q.count, 0);
  vscode.window.setStatusBarMessage(
    `$(search) ${total} match${total === 1 ? "" : "es"} in ${path.basename(result.sample)}`, 5000);
}

async function runQueryInTerminal() {
  const document = queryDocument();
  if (!document) {
    return;
  }
  await document.save();
  const { sample, flags, cwd } = samples.resolve(document);
  if (!terminal || terminal.exitStatus) {
    terminal = vscode.window.createTerminal({ name: "clang-query", cwd });
  }
  const parts = [
    quote(clangQuery()), "-f", quote(document.uri.fsPath), quote(sample),
    "--", ...flags.map(quote),
  ];
  terminal.show(true);
  terminal.sendText(parts.join(" "));
}

/** No argument: quick pick. A C/C++ file's Uri (context menus): use that file. */
async function selectSample(uri) {
  const document = queryDocument();
  if (!document) {
    vscode.window.showInformationMessage("astmatcher: open a .query file first.");
    return;
  }
  // Menus pass the clicked resource: a source file means "use this one", the
  // .query file itself (editor title bar) means "let me choose".
  if (uri instanceof vscode.Uri && SOURCE_EXTS.has(path.extname(uri.fsPath).toLowerCase())) {
    const cwd = samples.cwdFor(document);
    const p = uri.fsPath;
    await samples.set(document, p.startsWith(cwd + path.sep) ? path.relative(cwd, p) : p);
  } else {
    await samples.pick(document);
  }
  updateStatus();
}

/** The C/C++ file a source-file command was invoked on. */
function sourceUri(uri) {
  if (uri instanceof vscode.Uri) return uri;
  const editor = vscode.window.activeTextEditor;
  return editor ? editor.document.uri : undefined;
}

/** Create matchers/<name>.astmatcher aimed at a source file, and open it as a tab. */
async function newQueryForFile(uri) {
  const source = sourceUri(uri);
  if (!source || !SOURCE_EXTS.has(path.extname(source.fsPath).toLowerCase())) {
    vscode.window.showInformationMessage("astmatcher: open a C/C++ file to create a query for it.");
    return;
  }
  const folder = vscode.workspace.getWorkspaceFolder(source);
  const root = folder ? folder.uri.fsPath : path.dirname(source.fsPath);
  const dir = path.join(root, config().get("queriesDirectory") || "matchers");
  fs.mkdirSync(dir, { recursive: true });
  const stem = path.basename(source.fsPath, path.extname(source.fsPath));
  let target = path.join(dir, `${stem}.astmatcher`);
  for (let n = 2; fs.existsSync(target); n++) {
    target = path.join(dir, `${stem}-${n}.astmatcher`);
  }
  const rel = folder ? path.relative(root, source.fsPath) : source.fsPath;
  const flags = samples.defaultFlags(source.fsPath);
  fs.writeFileSync(target, `# sample: ${rel}${flags.length ? " " + flags.join(" ") : ""}\n`);
  const document = await vscode.workspace.openTextDocument(target);
  const editor = await vscode.window.showTextDocument(document, {
    viewColumn: vscode.ViewColumn.Active, preview: false,
  });
  await editor.insertSnippet(new vscode.SnippetString(
    "match ${1:functionDecl}(${2:isExpansionInMainFile()})$0\n"),
    new vscode.Position(1, 0));
}

/** Pick a query file and run it against this source file. */
async function runQueryOnFile(uri) {
  const source = sourceUri(uri);
  if (!source) return;
  const found = await vscode.workspace.findFiles("**/*.{query,astmatcher}",
                                                 "**/{node_modules,.git}/**", 2000);
  const open = vscode.workspace.textDocuments
    .filter((d) => d.languageId === "astmatcher").map((d) => d.uri);
  const seen = new Set();
  const uris = [...open, ...found.sort((a, b) => a.fsPath.localeCompare(b.fsPath))]
    .filter((u) => !seen.has(u.toString()) && seen.add(u.toString()));
  const folder = vscode.workspace.getWorkspaceFolder(source);
  const rel = (u) => (folder ? path.relative(folder.uri.fsPath, u.fsPath) : u.fsPath);
  const items = [
    { label: "$(new-file) New query for this file…", action: "new" },
    ...uris.map((u) => ({ label: path.basename(u.fsPath), description: path.dirname(rel(u)), uri: u })),
  ];
  const choice = await vscode.window.showQuickPick(items, {
    title: `Run a query on ${path.basename(source.fsPath)}`, matchOnDescription: true,
  });
  if (!choice) return;
  if (choice.action === "new") return newQueryForFile(source);
  const document = await vscode.workspace.openTextDocument(choice.uri);
  const cwd = samples.cwdFor(document);
  const p = source.fsPath;
  await samples.set(document, p.startsWith(cwd + path.sep) ? path.relative(cwd, p) : p);
  lastQueryDoc = document;
  await runQuery(choice.uri);
}

function updateStatus() {
  const document = queryDocument();
  const editor = vscode.window.activeTextEditor;
  if (!document || !editor || editor.document !== document) {
    statusItem.hide();
    return;
  }
  const target = samples.resolve(document);
  const exists = fs.existsSync(target.absolute);
  statusItem.text = `$(file-code) ${path.basename(target.sample)}${exists ? "" : " $(warning)"}`;
  statusItem.tooltip = new vscode.MarkdownString(
    `**clang-query sample** (${target.origin})\n\n\`${target.absolute}\`\n\n` +
    `flags: \`${target.flags.join(" ") || "(none)"}\`\n\nClick to choose another file.`);
  statusItem.show();
}

function quote(value) {
  return /^[\w@%+=:,.\/-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;
}

async function activate(context) {
  samples = new Samples(context);
  store = new ResultStore();
  matchesView = new MatchesView(context, store, { reveal: (sel) => reveal(store, sel) });
  queryDiagnostics = vscode.languages.createDiagnosticCollection("clang-query");
  statusItem = vscode.window.createStatusBarItem("astmatcher.sample",
                                                 vscode.StatusBarAlignment.Right, 100);
  statusItem.name = "AST Matcher Sample";
  statusItem.command = "astmatcher.selectSample";
  const highlighter = new Highlighter(store);
  const tree = new BindingsTree(store);

  const track = (editor) => {
    if (editor && editor.document.languageId === "astmatcher") lastQueryDoc = editor.document;
    updateStatus();
  };
  track(vscode.window.activeTextEditor);

  context.subscriptions.push(
    queryDiagnostics, statusItem, highlighter,
    vscode.window.registerWebviewViewProvider("astmatcher.matches", matchesView,
                                              { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.createTreeView("astmatcher.bindings", { treeDataProvider: tree,
                                                         showCollapseAll: true }),
    vscode.window.onDidChangeActiveTextEditor(track),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document === lastQueryDoc) queryDiagnostics.delete(e.document.uri);
    }),
    samples.onDidChange(updateStatus),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("astmatcher")) updateStatus();
    }),
    vscode.commands.registerCommand("astmatcher.runQuery", runQuery),
    vscode.commands.registerCommand("astmatcher.runQueryInTerminal", runQueryInTerminal),
    vscode.commands.registerCommand("astmatcher.newQueryForFile", newQueryForFile),
    vscode.commands.registerCommand("astmatcher.runQueryOnFile", runQueryOnFile),
    vscode.commands.registerCommand("astmatcher.selectSample", selectSample),
    vscode.commands.registerCommand("astmatcher.useAsSample",
      (uri) => selectSample(uri || (vscode.window.activeTextEditor || {}).document?.uri)),
    vscode.commands.registerCommand("astmatcher.editFlags", async () => {
      const document = queryDocument();
      if (document) await samples.editFlags(document);
    }),
    vscode.commands.registerCommand("astmatcher.revealBinding", (sel) => reveal(store, sel)),
    vscode.commands.registerCommand("astmatcher.toggleRoot", () => store.toggleRoot()),
    vscode.commands.registerCommand("astmatcher.toggleRoot.off", () => store.toggleRoot()),
    vscode.commands.registerCommand("astmatcher.clearResults", () => {
      store.set(undefined);
      queryDiagnostics.clear();
    }),
    vscode.commands.registerCommand("astmatcher.restartServer", async () => {
      if (client) {
        await client.stop();
        client = undefined;
      }
      await startServer(context);
    }),
  );
  await startServer(context);
}

async function deactivate() {
  if (client) {
    await client.stop();
  }
}

module.exports = { activate, deactivate };
