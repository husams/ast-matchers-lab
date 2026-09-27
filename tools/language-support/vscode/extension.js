// VS Code client for the AST matcher DSL.
//
// The grammar and snippets work on their own; this file adds the language
// server (completion, hover, signature help, diagnostics, semantic tokens) and
// running the open .query file through clang-query: the server runs it
// (`astmatcher/runQuery`) and the matches land in the "AST Matches" panel, the
// "AST Match Bindings" tree and as highlights in the sample file.

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");
const { Samples, SOURCE_EXTS } = require("./sample");
const { ResultStore, Highlighter, BindingsTree, MatchesView, reveal } = require("./results");
const { RunTarget } = require("./target");

let client;
let terminal;
let samples;
let store;
let matchesView;
let statusItem;
let queryDiagnostics;
let lastQueryDoc;             // the .query document commands act on from the panel
let targets;
let runSerial = 0;
let activeRunId;

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
  context.subscriptions.push(client.onNotification("astmatcher/queryProgress", (progress) => {
    if (!activeRunId || progress.runId !== activeRunId) return;
    if (progress.kind === "start") store.startStreaming(progress);
    else if (progress.kind === "file") store.appendStreamingFile(progress);
  }));
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
const SOURCE_GLOB = "**/*.{c,cc,cpp,cxx,c++,m,mm,cu,h,hh,hpp,hxx}";

function cacheLocation() {
  const configured = config().get("cacheLocation");
  if (configured) return resolveWorkspace(configured);
  const base = contextStoragePath;
  return base ? path.join(base, "cache") : path.join(process.cwd(), ".astmatcher-cache");
}
let contextStoragePath;

function getRunSettings() {
  const document = queryDocument();
  const sample = document && samples.resolve(document);
  const roots = vscode.workspace.workspaceFolders || [];
  const base = roots[0]?.uri.fsPath || process.cwd();
  const scope = config().get("scope") || "file";
  const configuredPath = config().get("targetPath");
  let targetPath = scope === "file"
    ? (sample && sample.absolute) || configuredPath || base
    : scope === "workspace" ? ""
      : configuredPath || (sample && sample.absolute) || base;
  return {
    visibleColumns: config().get("visibleColumns") || ["match", "kind", "semanticKind", "summary", "text", "location"],
    flags: sample ? sample.flags : (config().get("flags") || ["-std=c++23"]),
    compileCommands: config().get("compileCommands") || "",
    traversal: config().get("traversal") || "AsIs",
    exclusions: targets.exclusions(),
    cacheEnabled: config().get("cacheEnabled") === true,
    cacheLocation: cacheLocation(),
    scope,
    targetPath: scope === "workspace" ? ""
      : path.isAbsolute(targetPath) ? targetPath : path.resolve(base, targetPath),
  };
}

async function saveRunSettings(values = {}) {
  const workspaceTarget = vscode.ConfigurationTarget?.Workspace;
  const update = async (key, value) => config().update(key, value, workspaceTarget);
  let selectedScope;
  let selectedTargetPath;
  if (values.visibleColumns !== undefined && (!Array.isArray(values.visibleColumns) ||
      values.visibleColumns.some((v) => !["match", "kind", "semanticKind", "summary", "text", "location"].includes(v)))) {
    throw new Error("Visible columns must be selected from match, kind, semanticKind, summary, text, location.");
  }
  if (values.flags !== undefined && (!Array.isArray(values.flags) ||
      values.flags.some((v) => typeof v !== "string"))) throw new Error("Compiler flags must be an array of strings.");
  if (values.compileCommands !== undefined && typeof values.compileCommands !== "string") {
    throw new Error("compileCommands must be a path string.");
  }
  if (values.traversal !== undefined && !["AsIs", "IgnoreUnlessSpelledInSource"].includes(values.traversal)) {
    throw new Error("Traversal must be AsIs or IgnoreUnlessSpelledInSource.");
  }
  if (values.exclusions !== undefined && (!Array.isArray(values.exclusions) ||
      values.exclusions.some((v) => typeof v !== "string"))) throw new Error("Exclusions must be an array of glob strings.");
  if (values.cacheEnabled !== undefined && typeof values.cacheEnabled !== "boolean") {
    throw new Error("cacheEnabled must be boolean.");
  }
  if (values.cacheLocation !== undefined && typeof values.cacheLocation !== "string") {
    throw new Error("cacheLocation must be a path string.");
  }
  if (values.scope !== undefined && !["file", "directory", "workspace"].includes(values.scope)) {
    throw new Error("Scope must be file, directory, or workspace.");
  }
  if (values.targetPath !== undefined && typeof values.targetPath !== "string") {
    throw new Error("targetPath must be a path string.");
  }
  if (values.scope !== undefined || values.targetPath !== undefined) {
    const scope = values.scope || config().get("scope") || "file";
    selectedScope = scope;
    if (scope !== "workspace") {
      const currentPath = config().get("targetPath") || getRunSettings().targetPath;
      const targetPath = values.targetPath || currentPath;
      const base = (vscode.workspace.workspaceFolders || [])[0]?.uri.fsPath || process.cwd();
      const resolvedPath = path.isAbsolute(targetPath) ? path.resolve(targetPath) : path.resolve(base, targetPath);
      const stat = fs.statSync(resolvedPath);
      if (scope === "file" && !stat.isFile()) throw new Error("File scope requires a file.");
      if (scope === "directory" && !stat.isDirectory()) throw new Error("Directory scope requires a directory.");
      selectedTargetPath = resolvedPath;
    }
  }
  if (values.visibleColumns !== undefined) {
    await update("visibleColumns", [...new Set(values.visibleColumns)]);
  }
  if (values.flags !== undefined) {
    const document = queryDocument();
    if (document) {
      const current = samples.resolve(document);
      await samples.set(document, current.sample, values.flags);
    } else {
      await update("flags", values.flags);
    }
  }
  if (values.compileCommands !== undefined) {
    await update("compileCommands", values.compileCommands);
  }
  if (values.traversal !== undefined) {
    await update("traversal", values.traversal);
  }
  if (values.exclusions !== undefined) {
    await update("exclusions", values.exclusions);
  }
  if (values.cacheEnabled !== undefined) {
    await update("cacheEnabled", values.cacheEnabled);
  }
  if (values.cacheLocation !== undefined) {
    await update("cacheLocation", values.cacheLocation);
  }
  if (selectedScope) {
    if (selectedScope === "workspace") await update("scope", "workspace");
    else await targets.set(selectedScope, selectedTargetPath);
    if (selectedScope === "file") {
      const document = queryDocument();
      if (document) {
        const current = samples.resolve(document);
        await samples.set(document, selectedTargetPath,
          values.flags !== undefined ? values.flags : current.flags);
      }
    }
  }
  return getRunSettings();
}

async function setQueryTargetSample(document, targetPath) {
  await samples.setTarget(document, targetPath);
}

function flagsForNewQuery(samplePath) {
  const current = queryDocument();
  return current ? samples.resolve(current).flags : samples.defaultFlags(samplePath);
}

async function selectTarget() {
  const selectedScope = await vscode.window.showQuickPick([
    { label: "File", value: "file" },
    { label: "Directory", value: "directory" },
    { label: "Workspace", value: "workspace" },
  ], { title: "Choose AST Matcher run scope" });
  if (!selectedScope) return;
  const scope = selectedScope.value;
  let targetPath;
  if (scope === "workspace") {
    const roots = vscode.workspace.workspaceFolders || [];
    targetPath = roots[0]?.uri.fsPath;
  } else if (scope === "directory") {
    const uris = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false,
      canSelectMany: false, defaultUri: rootsUri() });
    targetPath = uris && uris[0] && uris[0].fsPath;
  } else {
    const uris = await vscode.window.showOpenDialog({ canSelectFolders: false, canSelectFiles: true,
      canSelectMany: false, defaultUri: rootsUri(), filters: { "C / C++ / ObjC / CUDA":
        ["c", "cc", "cpp", "cxx", "c++", "m", "mm", "cu", "h", "hh", "hpp", "hxx"] } });
    targetPath = uris && uris[0] && uris[0].fsPath;
  }
  if (!targetPath) return;
  await targets.set(scope, targetPath);
  if (scope === "file") {
    const document = queryDocument();
    if (document && samples.resolve(document).absolute !== path.resolve(targetPath)) {
      await setQueryTargetSample(document, targetPath);
    }
  }
  updateStatus();
  return getRunSettings();
}

function rootsUri() {
  return (vscode.workspace.workspaceFolders || [])[0]?.uri;
}

function createRunRequest(document, sample, target) {
  return {
    textDocument: { uri: document.uri.toString() },
    sample: sample.absolute,
    flags: sample.flags,
    clangQuery: clangQuery(),
    cwd: sample.cwd,
    target,
    exclusions: targets.exclusions(),
    compileCommands: config().get("compileCommands") || "",
    traversal: config().get("traversal") || "AsIs",
    cache: { enabled: config().get("cacheEnabled") === true, location: cacheLocation() },
  };
}

async function resolveSampleForTarget(sample, target) {
  if (target.scope === "file" || fs.existsSync(sample.absolute)) return sample;
  const candidates = target.scope === "directory"
    ? await vscode.workspace.findFiles(new vscode.RelativePattern(vscode.Uri.file(target.path), SOURCE_GLOB),
      "**/{node_modules,build,.git,.cache}/**", 1)
    : await vscode.workspace.findFiles(SOURCE_GLOB, "**/{node_modules,build,.git,.cache}/**", 1);
  if (!candidates.length) return sample;
  const absolute = candidates[0].fsPath;
  return { ...sample, absolute, sample: absolute,
    flags: sample.origin === "settings" ? samples.defaultFlags(absolute) : sample.flags };
}

async function runWithScope(scope, uri) {
  let p = uri instanceof vscode.Uri ? uri.fsPath : undefined;
  if (!p && scope === "file") {
    const document = queryDocument();
    p = document ? samples.resolve(document).absolute : config().get("targetPath");
  }
  if (!p && scope === "directory") {
    const uris = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false,
      canSelectMany: false, defaultUri: rootsUri() });
    p = uris && uris[0] && uris[0].fsPath;
  }
  if (!p && scope === "workspace") p = (vscode.workspace.workspaceFolders || [])[0]?.uri.fsPath;
  if (!p) return;
  await targets.set(scope, p);
  if (scope === "file") {
    const document = queryDocument();
    if (document && samples.resolve(document).absolute !== path.resolve(p)) {
      await setQueryTargetSample(document, p);
    }
  }
  return runQuery();
}

/** Menus pass the clicked resource; run that query file if it is one. */
async function runQuery(arg) {
  const serial = ++runSerial;
  activeRunId = undefined;
  const document = arg instanceof vscode.Uri && QUERY_EXTS.has(path.extname(arg.fsPath))
    ? await vscode.workspace.openTextDocument(arg)
    : queryDocument();
  if (!document) {
    vscode.window.showInformationMessage("astmatcher: open a .query file to run it.");
    return;
  }
  if (!client || !client.isRunning()) {
    const settings = getRunSettings();
    const needsServer = settings.scope !== "file" || settings.compileCommands ||
      settings.traversal !== "AsIs" || settings.exclusions.length || settings.cacheEnabled;
    if (needsServer) {
      vscode.window.showWarningMessage(
        "astmatcher: directory/workspace runs and configured run options require the language server.");
      return;
    }
    return runQueryInTerminal();
  }
  let sample = samples.resolve(document);
  const target = targets.resolve(sample.absolute);
  sample = await resolveSampleForTarget(sample, target);
  const checkedPath = target.scope === "file" ? sample.absolute : target.path;
  if (!fs.existsSync(checkedPath)) {
    const choice = await vscode.window.showWarningMessage(
      `astmatcher: run target not found: ${checkedPath}`, "Select Run Target…");
    if (choice) await selectTarget();
    return;
  }
  const runningLabel = target.scope === "workspace"
    ? "all workspace folders" : path.basename(target.path);
  const runId = crypto.randomUUID();
  activeRunId = runId;
  store.setRunning({ sample: runningLabel, scope: target.scope,
                     targetPath: target.path });
  matchesView.show();
  let result;
  try {
    result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: "clang-query" },
      () => client.sendRequest("astmatcher/runQuery",
        { ...createRunRequest(document, sample, target), runId }));
  } catch (err) {
    if (serial !== runSerial) return;
    activeRunId = undefined;
    store.set(undefined);
    vscode.window.showErrorMessage(`astmatcher: run failed: ${err.message || err}`);
    return;
  }
  if (serial !== runSerial) return;
  activeRunId = undefined;
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
  const settings = getRunSettings();
  if (settings.scope !== "file" || settings.compileCommands || settings.traversal !== "AsIs" ||
      settings.exclusions.length || settings.cacheEnabled) {
    vscode.window.showWarningMessage(
      "astmatcher: terminal runs support file scope and compiler flags only; use Run Query for configured options.");
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
  if ((config().get("scope") || "file") === "file") {
    const selected = samples.resolve(document).absolute;
    if (fs.existsSync(selected) && fs.statSync(selected).isFile()) await targets.set("file", selected);
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
  const flags = flagsForNewQuery(source.fsPath);
  fs.writeFileSync(target, `# sample: ${rel}${flags.length ? " " + flags.join(" ") : ""}\n`);
  const document = await vscode.workspace.openTextDocument(target);
  const editor = await vscode.window.showTextDocument(document, {
    viewColumn: vscode.ViewColumn.Active, preview: false,
  });
  await editor.insertSnippet(new vscode.SnippetString(
    "match ${1:functionDecl}(${2:isExpansionInMainFile()})$0\n"),
    new vscode.Position(1, 0));
}

async function createAndRunForTarget(uri) {
  const resource = sourceUri(uri);
  if (!resource) return;
  const fsPath = resource.fsPath;
  const isDirectory = fs.existsSync(fsPath) && fs.statSync(fsPath).isDirectory();
  const scope = isDirectory ? "directory" : "file";
  if (!isDirectory && !SOURCE_EXTS.has(path.extname(fsPath).toLowerCase())) return;
  let samplePath = fsPath;
  if (isDirectory) {
    const candidates = await vscode.workspace.findFiles(
      new vscode.RelativePattern(resource, SOURCE_GLOB), "**/{node_modules,build,.git,.cache}/**", 1);
    if (!candidates.length) {
      vscode.window.showInformationMessage("astmatcher: no C/C++ source files found in this directory.");
      return;
    }
    samplePath = candidates[0].fsPath;
  }
  const folder = vscode.workspace.getWorkspaceFolder(resource);
  const root = folder ? folder.uri.fsPath : (isDirectory ? fsPath : path.dirname(fsPath));
  const dir = path.join(root, config().get("queriesDirectory") || "matchers");
  fs.mkdirSync(dir, { recursive: true });
  const stem = isDirectory ? path.basename(fsPath) : path.basename(fsPath, path.extname(fsPath));
  let queryPath = path.join(dir, `${stem}.astmatcher`);
  for (let n = 2; fs.existsSync(queryPath); n++) queryPath = path.join(dir, `${stem}-${n}.astmatcher`);
  const rel = folder ? path.relative(root, samplePath) : samplePath;
  const flags = flagsForNewQuery(samplePath);
  fs.writeFileSync(queryPath, `# sample: ${rel}${flags.length ? " " + flags.join(" ") : ""}\n`);
  const document = await vscode.workspace.openTextDocument(queryPath);
  const editor = await vscode.window.showTextDocument(document, {
    viewColumn: vscode.ViewColumn.Active, preview: false,
  });
  await editor.insertSnippet(new vscode.SnippetString(
    "match ${1:functionDecl}(${2:isExpansionInMainFile()})$0\n"), new vscode.Position(1, 0));
  await document.save();
  lastQueryDoc = document;
  await targets.set(scope, fsPath);
  return runQuery(document.uri);
}

/** Pick a query file and run it against this source file. */
async function runQueryOnFile(uri) {
  const source = sourceUri(uri);
  if (!source) return;
  const isDirectory = fs.existsSync(source.fsPath) && fs.statSync(source.fsPath).isDirectory();
  let samplePath = source.fsPath;
  if (isDirectory) {
    const candidates = await vscode.workspace.findFiles(
      new vscode.RelativePattern(source, SOURCE_GLOB), "**/{node_modules,build,.git,.cache}/**", 1);
    if (!candidates.length) {
      vscode.window.showInformationMessage("astmatcher: no C/C++ source files found in this directory.");
      return;
    }
    samplePath = candidates[0].fsPath;
  }
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
    { label: "$(new-file) New query and run…", action: "new" },
    ...uris.map((u) => ({ label: path.basename(u.fsPath), description: path.dirname(rel(u)), uri: u })),
  ];
  const choice = await vscode.window.showQuickPick(items, {
    title: `Run a query on ${path.basename(source.fsPath)}`, matchOnDescription: true,
  });
  if (!choice) return;
  if (choice.action === "new") return createAndRunForTarget(source);
  const document = await vscode.workspace.openTextDocument(choice.uri);
  const cwd = samples.cwdFor(document);
  const p = samplePath;
  await setQueryTargetSample(document, p.startsWith(cwd + path.sep) ? path.relative(cwd, p) : p);
  await targets.set(isDirectory ? "directory" : "file", source.fsPath);
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
  const runTarget = targets.resolve(target.absolute);
  const exists = fs.existsSync(target.absolute);
  statusItem.text = `$(search) ${runTarget.scope}: ${path.basename(runTarget.path)}${exists ? "" : " $(warning)"}`;
  statusItem.tooltip = new vscode.MarkdownString(
    `**clang-query sample** (${target.origin})\n\n\`${target.absolute}\`\n\n` +
    `**run scope:** ${runTarget.scope}\n\n\`${runTarget.path}\`\n\n` +
    `flags: \`${target.flags.join(" ") || "(none)"}\`\n\nClick to choose another file.`);
  statusItem.show();
}

function quote(value) {
  return /^[\w@%+=:,.\/-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;
}

async function activate(context) {
  contextStoragePath = context.globalStorageUri && context.globalStorageUri.fsPath;
  samples = new Samples(context);
  targets = new RunTarget();
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
    vscode.commands.registerCommand("astmatcher.runFile", (uri) => runWithScope("file", uri)),
    vscode.commands.registerCommand("astmatcher.runDirectory", (uri) => runWithScope("directory", uri)),
    vscode.commands.registerCommand("astmatcher.runWorkspace", (uri) => runWithScope("workspace", uri)),
    vscode.commands.registerCommand("astmatcher.selectTarget", selectTarget),
    vscode.commands.registerCommand("astmatcher.getRunSettings", getRunSettings),
    vscode.commands.registerCommand("astmatcher.saveRunSettings", saveRunSettings),
    vscode.commands.registerCommand("astmatcher.openSettings", () => matchesView.showSettings()),
    vscode.commands.registerCommand("astmatcher.createAndRunQuery", createAndRunForTarget),
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

module.exports = { activate, deactivate, createRunRequest, resolveSampleForTarget };
