"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

test("activation starts the language client for saved and untitled matcher documents", async () => {
  let clientOptions;
  let started = false;
  const registered = new Map();
  const notifications = [];
  const clientNotifications = new Map();
  const statusItems = [];
  const errors = [];
  let resolveRequest;
  let rejectRequest;
  let lastRunRequest;
  let cancelWasEnabledAtEnqueue;
  let failCancellationNotification = false;
  let onTextDocumentChange;
  let resultStore;
  let samplePath = __filename;
  const stored = {};
  const information = [];
  const explorerOpens = [];
  let tempSourceDir;

  class LanguageClient {
    constructor(_id, _name, _serverOptions, options) { clientOptions = options; }
    async start() { started = true; }
    async stop() {}
    isRunning() { return true; }
    onNotification(method, callback) { clientNotifications.set(method, callback); return disposable; }
    sendRequest(_method, params) {
      lastRunRequest = params;
      cancelWasEnabledAtEnqueue = statusItems.find((item) => item.name === "AST Matcher Query Progress")?.command === "astmatcher.cancelQuery";
      return new Promise((resolve, reject) => { resolveRequest = resolve; rejectRequest = reject; });
    }
    async sendNotification(method, params) {
      notifications.push({ method, params });
      if (failCancellationNotification) throw new Error("notification transport failed");
    }
  }

  class EventEmitter {
    constructor() { this.event = () => ({ dispose() {} }); }
    fire() {}
  }

  const disposable = { dispose() {} };
  const vscode = {
    EventEmitter,
    StatusBarAlignment: { Right: 1 },
    workspace: {
      workspaceFolders: [{ uri: { fsPath: path.resolve(__dirname, "../../../../") } }],
      textDocuments: [],
      getConfiguration: () => ({
        get: (key) => stored[key] ?? ({
        "server.enabled": true,
        "server.path": path.resolve(__dirname, "../../astmatcher-lsp/bin/astmatcher-lsp"),
        "server.python": "python3",
        "nativeServerPath": "tools/language-support/native/build/astmatcher-native",
        "flags": ["-std=c++23"], "traversal": "AsIs", "exclusions": [],
        "visibleColumns": ["match", "kind", "semanticKind", "summary", "text", "location"],
        "cacheEnabled": false, "cacheLocation": "", "compileCommands": "", "scope": "file",
      })[key],
        update: async (key, value) => { stored[key] = value; },
      }),
      getWorkspaceFolder: () => undefined,
      findFiles: async () => [{ fsPath: __filename }],
      onDidChangeTextDocument: (callback) => { onTextDocumentChange = callback; return disposable; },
      onDidChangeConfiguration: () => disposable,
    },
    window: {
      activeTextEditor: undefined,
      showInformationMessage: (message) => { information.push(message); },
      showErrorMessage: (message) => { errors.push(message); },
      showWarningMessage: async () => undefined,
      createStatusBarItem: () => { const item = { hide() {}, show() {} }; statusItems.push(item); return item; },
      withProgress: (_options, task) => task(),
      setStatusBarMessage() {},
      createOutputChannel: () => ({ clear() {}, append() {}, appendLine() {}, show() {}, dispose() {} }),
      registerWebviewViewProvider: () => disposable,
      createTreeView: () => disposable,
      onDidChangeActiveTextEditor: () => disposable,
    },
    languages: {
      createDiagnosticCollection: () => ({ ...disposable, delete() {}, set() {}, clear() {} }),
    },
    ConfigurationTarget: { Workspace: 2 },
    ProgressLocation: { Window: 1 },
    commands: { executeCommand() {}, registerCommand: (name, callback) => { registered.set(name, callback); return disposable; } },
    MarkdownString: class MarkdownString {},
    RelativePattern: class RelativePattern { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    Uri: class Uri {
      static file(fsPath) { return { fsPath, toString: () => `file://${fsPath}` }; }
    },
  };

  const sample = {
    Samples: class Samples {
      constructor() { this.onDidChange = () => disposable; }
      resolve() { return { absolute: samplePath, cwd: path.dirname(samplePath), flags: ["-std=c++23"], origin: "settings" }; }
      defaultFlags() { return ["-DVALUE=a b", "-Iinclude path"]; }
    },
    SOURCE_EXTS: new Set([".cpp", ".hpp"]),
  };
  const results = Object.fromEntries(
    ["ResultStore", "Highlighter", "BindingsTree", "MatchesView"].map((name) => [
      name, class { constructor() {} },
    ]),
  );
  results.MatchesView = class { constructor() {} show() {} };
  results.reveal = () => {};
  results.ResultStore = class {
    constructor() { this.generation = 2; this.result = { cwd: "/workspace", flags: ["-std=c++23"] }; this.appendCount = 0; resultStore = this; }
    setRunning(info) { this.running = info; }
    setCancellable(cancellable) { this.running.cancellable = cancellable; }
    startStreaming() {}
    appendStreamingFile() { this.appendCount = (this.appendCount || 0) + 1; }
    requestCancellation() { this.cancelRequested = true; }
    cancelRequestFailed() { this.cancelRequested = false; }
    set(result) { this.result = result; this.running = false; }
    binding(sel) { return sel.q === 0 ? { kind: "CXXRecordDecl", file: "/workspace/source.cpp",
      range: { start: { line: 1, character: 0 }, end: { line: 4, character: 1 } } } : undefined; }
  };

  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === "vscode") return vscode;
    if (request === "vscode-languageclient/node") {
      return { LanguageClient, TransportKind: { stdio: 1 } };
    }
    if (request === "./sample") return sample;
    if (request === "./results") return results;
    if (request === "./record-explorer") return { RecordExplorer: class {
      async open(target, options) { explorerOpens.push({ target, options }); }
    } };
    return originalLoad.call(this, request, parent, isMain);
  };

  try {
    const extensionPath = require.resolve("../extension");
    delete require.cache[extensionPath];
    const extension = require("../extension");
    await extension.activate({ subscriptions: [], workspaceState: {},
      globalStorageUri: { fsPath: "/extension/storage" } });

    const selector = clientOptions.documentSelector;
    const matches = (scheme, language) => selector.some((entry) =>
      entry.scheme === scheme && entry.language === language);
    assert.equal(matches("file", "astmatcher"), true);
    assert.equal(matches("untitled", "astmatcher"), true);
    assert.equal(matches("file", "cpp"), false);
    assert.equal(matches("untitled", "plaintext"), false);
    assert.equal(started, true);
    for (const command of [
      "astmatcher.runFile", "astmatcher.runDirectory", "astmatcher.runWorkspace",
      "astmatcher.selectTarget", "astmatcher.getRunSettings", "astmatcher.saveRunSettings",
      "astmatcher.openSettings", "astmatcher.createAndRunQuery", "astmatcher.exploreRecord",
      "astmatcher.cancelQuery",
    ]) assert.equal(registered.has(command), true, `missing command ${command}`);
    vscode.window.activeTextEditor = { document: { uri: { fsPath: "/workspace/source.cpp" },
      languageId: "cpp" }, selection: {
      start: { line: 2, character: 1 }, end: { line: 2, character: 1 },
    } };
    await registered.get("astmatcher.exploreRecord")({ q: 99, m: 0, b: 0 });
    assert.equal(explorerOpens.length, 0, "an expired result must not inspect the active editor cursor");
    assert.match(information.at(-1), /stale/);
    await registered.get("astmatcher.exploreRecord")({ sel: { q: 0, m: 0, b: 0 }, generation: 1 });
    assert.equal(explorerOpens.length, 0, "reused selector coordinates from an older run must be rejected");
    assert.match(information.at(-1), /stale/);
    await registered.get("astmatcher.exploreRecord")({ sel: { q: 0, m: 0, b: 0 }, generation: 2 });
    assert.equal(explorerOpens.length, 1, "current generation may inspect the selected binding");
    const header = "/workspace/include/inner.hpp";
    const translationUnit = "/workspace/main.cpp";
    const range = { start: { line: 6, character: 0 }, end: { line: 8, character: 1 } };
    const headerBinding = { kind: "CXXRecordDecl", file: header, range,
      translationUnit, qualifiedName: "app::Child", recordIdentity: "app::Child" };
    resultStore.result = { cwd: "/workspace", flags: ["-std=c++23", "-DHEADER=1"],
      bindings: { child: [headerBinding] } };
    resultStore.selected = { q: 0, m: 0, b: 0, generation: 2 };
    resultStore.binding = () => headerBinding;
    const headerDocument = { uri: { fsPath: header }, languageId: "cpp", version: 1,
      lineAt: (line) => ({ text: line === 7 ? "class Box {};" :
        "class Child { class Nested {}; };" }) };
    vscode.window.activeTextEditor = { document: headerDocument,
      selection: { start: { ...range.start }, end: { ...range.end } } };
    await registered.get("astmatcher.exploreRecord")();
    assert.deepEqual(explorerOpens.at(-1).target, headerBinding,
      "exploring an opened result retains its record identity and original translation unit");
    assert.deepEqual(explorerOpens.at(-1).options.flags, ["-std=c++23", "-DHEADER=1"]);
    assert.equal(explorerOpens.at(-1).options.cwd, "/workspace");
    resultStore.selected = undefined;
    vscode.window.activeTextEditor.selection = {
      start: { line: 6, character: 8 }, end: { line: 6, character: 8 } };
    await registered.get("astmatcher.exploreRecord")();
    assert.deepEqual(explorerOpens.at(-1).target, headerBinding,
      "a cursor on the matched record can recover unique query provenance");
    vscode.window.activeTextEditor.selection = {
      start: { line: 6, character: 26 }, end: { line: 6, character: 26 } };
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, header,
      "a cursor on a nested class must not reuse the outer record binding");
    const templateBinding = { ...headerBinding,
      range: { start: { line: 7, character: 0 }, end: { line: 7, character: 12 } },
      qualifiedName: "app::Box<other::Type>", recordIdentity: "app::Box<other::Type>" };
    resultStore.result.bindings = { box: [templateBinding] };
    vscode.window.activeTextEditor.selection = {
      start: { line: 7, character: 7 }, end: { line: 7, character: 7 } };
    await registered.get("astmatcher.exploreRecord")();
    assert.deepEqual(explorerOpens.at(-1).target, templateBinding,
      "a namespace inside template arguments must not hide the record name");
    vscode.window.activeTextEditor.selection = {
      start: { line: 6, character: 8 }, end: { line: 6, character: 8 } };
    resultStore.result.bindings = { child: [headerBinding,
      { ...headerBinding, translationUnit: "/workspace/other.cpp" }] };
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, header,
      "ambiguous query provenance must not choose an arbitrary translation unit");
    resultStore.result = { bindings: {} };
    vscode.window.activeTextEditor.selection = {
      start: { line: 12, character: 2 }, end: { line: 12, character: 2 } };
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, header,
      "an unrelated cursor keeps the original editor-only behavior");
    assert.deepEqual(explorerOpens.at(-1).options.flags, ["-DVALUE=a b", "-Iinclude path"]);
    const settings = await registered.get("astmatcher.getRunSettings")();
    assert.deepEqual(Object.keys(settings).sort(), [
      "cacheEnabled", "cacheLocation", "compileCommands", "exclusions", "flags",
      "scope", "targetPath", "traversal", "visibleColumns",
    ].sort());
    assert.equal(settings.scope, "file");
    await assert.rejects(registered.get("astmatcher.saveRunSettings")({
      compileCommands: "compile_commands.json", traversal: "invalid",
    }));
    assert.equal(stored.compileCommands, undefined, "invalid updates do not partially save settings");
    await registered.get("astmatcher.saveRunSettings")({
      flags: ["-DVALUE=a b", "-Iinclude path"], compileCommands: "/external/compile_commands.json",
      traversal: "IgnoreUnlessSpelledInSource", exclusions: ["build/**"], cacheEnabled: true,
      cacheLocation: "/external/ast-cache",
    });
    const pickedSample = await extension.resolveSampleForTarget(
      { absolute: "/external/query/missing-sample.cpp", cwd: "/external/query",
        flags: ["-DVALUE=a b", "-Iinclude path"], origin: "settings" },
      { scope: "directory", path: path.dirname(__filename) },
    );
    const request = extension.createRunRequest(
      { uri: { toString: () => "file:///external/query.astmatcher" } },
      pickedSample,
      { scope: "directory", path: path.dirname(__filename), roots: ["/workspace/root-a", "/workspace/root-b"] },
    );
    assert.equal(request.sample, __filename, "external queries fall back to a real TU in the selected directory");
    assert.deepEqual(request.target.roots, ["/workspace/root-a", "/workspace/root-b"]);
    assert.deepEqual(request.flags, ["-DVALUE=a b", "-Iinclude path"]);
    assert.deepEqual(request.exclusions, ["build/**"]);
    assert.equal(request.compileCommands, "/external/compile_commands.json");
    assert.equal(request.traversal, "IgnoreUnlessSpelledInSource");
    assert.deepEqual(request.cache, { enabled: true, location: "/external/ast-cache" });
    const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
    assert.equal(request.nativeServerPath,
      path.join(workspaceRoot, "tools/language-support/native/build/astmatcher-native"));
    assert.equal(Object.hasOwn(request, "clangQuery"), false,
      "Run Query must not send the old clang-query executable path");
    await registered.get("astmatcher.saveRunSettings")({ scope: "workspace", targetPath: __filename });
    const workspaceSettings = await registered.get("astmatcher.getRunSettings")();
    assert.equal(workspaceSettings.scope, "workspace");
    assert.equal(workspaceSettings.targetPath, "", "workspace scope represents all roots without a single target path");
    await registered.get("astmatcher.saveRunSettings")({
      scope: "file", targetPath: path.relative(workspaceRoot, __filename),
    });
    assert.equal((await registered.get("astmatcher.getRunSettings")()).targetPath, __filename,
      "a selected file replaces a stale path and relative paths resolve from the workspace root");
    vscode.window.activeTextEditor = { document: { uri: { fsPath: "/workspace/query.astmatcher",
      toString: () => "file:///workspace/query.astmatcher" }, languageId: "astmatcher" } };
    const running = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    const runId = lastRunRequest.runId;
    assert.equal(cancelWasEnabledAtEnqueue, false, "the request is enqueued before the status bar can cancel it");
    assert.equal(resultStore.running.cancellable, true);
    samplePath = "/workspace/missing.cpp";
    await registered.get("astmatcher.runQuery")();
    await registered.get("astmatcher.cancelQuery")();
    await registered.get("astmatcher.cancelQuery")();
    assert.deepEqual(notifications, [{ method: "astmatcher/cancelQuery", params: { runId } }]);
    clientNotifications.get("astmatcher/queryProgress")({ kind: "file", runId,
      file: "/workspace/late.cpp", queries: [], bindings: {}, errors: [] });
    assert.equal(resultStore.cancelRequested, true);
    assert.equal(resultStore.appendCount, 0, "progress arriving after cancellation is ignored");
    resolveRequest({ ok: false, cancelled: true, sample: __filename, flags: [], queries: [],
      bindings: {}, files: [__filename], errors: [], durationMs: 1 });
    await running;
    assert.equal(resultStore.result.cancelled, true, "partial completion remains marked cancelled");

    samplePath = __filename;
    const failingRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    failCancellationNotification = true;
    await registered.get("astmatcher.cancelQuery")();
    assert.equal(resultStore.cancelRequested, false, "failed cancel notification permits retry");
    assert.equal(resultStore.running.cancellable, true);
    failCancellationNotification = false;
    await registered.get("astmatcher.cancelQuery")();
    rejectRequest(new Error("LSP disconnected"));
    await failingRun;
    assert.ok(errors.some((message) => message.includes("run failed: LSP disconnected")),
      "a rejected query reports its actual transport failure after cancellation was requested");
    tempSourceDir = fs.mkdtempSync(path.join(os.tmpdir(), "astmatcher-editor-record-"));
    const onDiskHeader = path.join(tempSourceDir, "inner.hpp");
    fs.writeFileSync(onDiskHeader, "class Child {};\n");
    const onDiskBinding = { ...headerBinding, file: onDiskHeader };
    const onDiskDocument = { ...headerDocument, uri: { fsPath: onDiskHeader }, version: 1 };
    vscode.workspace.textDocuments = [onDiskDocument];
    const freshRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    resolveRequest({ ok: true, sample: __filename, cwd: "/workspace",
      flags: ["-std=c++23", "-DHEADER=1"], queries: [{ count: 1, matches: [] }],
      bindings: { child: [onDiskBinding] }, files: [__filename], errors: [], durationMs: 1 });
    await freshRun;
    vscode.window.activeTextEditor = { document: onDiskDocument,
      selection: { start: { ...range.start }, end: { ...range.end } } };
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, translationUnit);
    onDiskDocument.version = 2;
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, onDiskHeader,
      "an edited header invalidates the saved record identity even after the result selection");
    onDiskDocument.version = 1;
    onTextDocumentChange({ document: onDiskDocument });
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, onDiskHeader,
      "a document edit remains invalid after save or a version reset");
    vscode.window.activeTextEditor = { document: { uri: { fsPath: "/workspace/query.astmatcher",
      toString: () => "file:///workspace/query.astmatcher" }, languageId: "astmatcher" } };
    const externalEditRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    resolveRequest({ ok: true, sample: __filename, cwd: "/workspace",
      flags: ["-std=c++23", "-DHEADER=1"], queries: [{ count: 1, matches: [] }],
      bindings: { child: [onDiskBinding] }, files: [__filename], errors: [], durationMs: 1 });
    await externalEditRun;
    vscode.window.activeTextEditor = { document: onDiskDocument,
      selection: { start: { ...range.start }, end: { ...range.end } } };
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, translationUnit);
    fs.appendFileSync(onDiskHeader, "// changed externally\n");
    await registered.get("astmatcher.exploreRecord")();
    assert.equal(explorerOpens.at(-1).target.translationUnit, onDiskHeader,
      "an external file edit invalidates the saved record identity");
    await extension.deactivate();
  } finally {
    if (tempSourceDir) fs.rmSync(tempSourceDir, { recursive: true, force: true });
    Module._load = originalLoad;
    delete require.cache[require.resolve("../extension")];
  }
});

test("Explorer file menu does not expose cursor-only Explore Record", () => {
  const contribution = require("../package.json").contributes;
  assert.equal(contribution.menus["astmatcher.source"].some((entry) =>
    entry.command === "astmatcher.exploreRecord"), false);
  assert.equal(contribution.menus["editor/context"].some((entry) =>
    entry.command === "astmatcher.exploreRecord"), true);
});
