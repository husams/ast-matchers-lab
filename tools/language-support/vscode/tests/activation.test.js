"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

test("activation starts the language client for saved and untitled matcher documents", async () => {
  let clientOptions;
  let started = false;
  let clientRunning = true;
  let matchesShown = 0;
  const diagnosticEntries = [];
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
  let resultStore;
  let samplePath = __filename;
  const stored = {};
  const information = [];
  const explorerOpens = [];

  class LanguageClient {
    constructor(_id, _name, _serverOptions, options) { clientOptions = options; }
    async start() { started = true; }
    async stop() {}
    isRunning() { return clientRunning; }
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
      getConfiguration: () => ({
        get: (key) => stored[key] ?? ({
        "server.enabled": true,
        "server.path": path.resolve(__dirname, "../../astmatcher-lsp/bin/astmatcher-lsp"),
        "server.python": "python3",
        "nativeServerPath": "tools/language-support/native/build/astmatcher-native",
        "flags": ["-std=c++23"], "traversal": "AsIs", "exclusions": [],
        "visibleColumns": ["match", "kind", "summary", "text", "location"],
        "cacheEnabled": false, "cacheLocation": "", "compileCommands": "", "scope": "file",
      })[key],
        update: async (key, value) => { stored[key] = value; },
      }),
      getWorkspaceFolder: () => undefined,
      findFiles: async () => [{ fsPath: __filename }],
      onDidChangeTextDocument: () => disposable,
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
      createOutputChannel: () => ({
        clear() { diagnosticEntries.length = 0; },
        append(value) { diagnosticEntries.push(value); },
        appendLine(value) { diagnosticEntries.push(value); },
        show() {}, dispose() {},
      }),
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
    SOURCE_EXTS: new Set([".cpp"]),
  };
  const results = Object.fromEntries(
    ["ResultStore", "Highlighter", "BindingsTree", "MatchesView"].map((name) => [
      name, class { constructor() {} },
    ]),
  );
  results.MatchesView = class { constructor() {} show() { matchesShown++; } };
  results.reveal = () => {};
  results.ResultStore = class {
    constructor() { this.generation = 2; this.result = { cwd: "/workspace", flags: ["-std=c++23"] }; this.appendCount = 0; resultStore = this; }
    setRunning(info) { this.running = info; this.failure = undefined; }
    setCancellable(cancellable) { this.running.cancellable = cancellable; }
    startStreaming() {}
    appendStreamingFile() { this.appendCount = (this.appendCount || 0) + 1; }
    requestCancellation() { this.cancelRequested = true; }
    cancelRequestFailed() { this.cancelRequested = false; }
    set(result, failure) { this.result = result; this.running = false; this.failure = failure; }
    setFailure(failure) { this.set(undefined, failure); }
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
      async open(target) { explorerOpens.push(target); }
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

    samplePath = "/workspace/missing.cpp";
    await registered.get("astmatcher.runQuery")();
    assert.match(resultStore.failure.message, /run target was not found/);
    assert.equal(resultStore.failure.action, "select-target");
    samplePath = __filename;
    clientRunning = false;
    await registered.get("astmatcher.runQuery")();
    assert.match(resultStore.failure.message, /language server is unavailable/);
    assert.equal(resultStore.failure.action, "runtime-settings");
    assert.ok(matchesShown >= 2, "preflight failures open the persistent matches panel");
    clientRunning = true;

    const failingRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    failCancellationNotification = true;
    await registered.get("astmatcher.cancelQuery")();
    assert.equal(resultStore.cancelRequested, false, "failed cancel notification permits retry");
    assert.equal(resultStore.running.cancellable, true);
    failCancellationNotification = false;
    await registered.get("astmatcher.cancelQuery")();
    rejectRequest(new Error("LSP disconnected; token=examplecredential"));
    await failingRun;
    assert.equal(resultStore.failure.action, "diagnostics");
    assert.match(resultStore.failure.message, /query request failed/i);
    assert.ok(errors.some((message) => message.includes("open AST Matcher Diagnostics")),
      "a rejected query offers a persistent, actionable error after cancellation was requested");
    assert.ok(errors.every((message) => !message.includes("LSP disconnected")),
      "the notification stays concise while Diagnostics retains the backend detail");
    assert.ok(diagnosticEntries.some((entry) => entry.includes("LSP disconnected")),
      "Diagnostics preserves the actual transport failure");
    assert.ok(diagnosticEntries.every((entry) => !entry.includes("examplecredential")),
      "Diagnostics redacts token values from transport errors");

    const errorResultRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    resolveRequest({ ok: false, sample: __filename, flags: [], queries: [], bindings: {},
      files: [], errors: [{ message: "native runner unavailable" }], durationMs: 1 });
    await errorResultRun;
    assert.equal(resultStore.failure.action, "diagnostics");
    assert.equal(resultStore.result.errors.length, 1, "server diagnostics remain available");
    const parseResultRun = registered.get("astmatcher.runQuery")();
    await new Promise(setImmediate);
    resolveRequest({ ok: false, sample: __filename, flags: [], queries: [], bindings: {},
      files: [__filename], exitCode: 1,
      errors: [{ file: __filename, message: "Clang failed to parse the source file" }], durationMs: 1 });
    await parseResultRun;
    assert.equal(resultStore.failure, undefined,
      "ordinary source parse diagnostics stay in the status area without a panel error");
    samplePath = "/workspace/missing.cpp";
    await registered.get("astmatcher.runQuery")();
    assert.equal(diagnosticEntries.length, 0, "a preflight error clears stale source diagnostics");
    await extension.deactivate();
  } finally {
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
