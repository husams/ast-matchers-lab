"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

test("activation starts the language client for saved and untitled matcher documents", async () => {
  let clientOptions;
  let started = false;
  const registered = new Map();
  const stored = {};
  const information = [];
  const explorerOpens = [];

  class LanguageClient {
    constructor(_id, _name, _serverOptions, options) { clientOptions = options; }
    async start() { started = true; }
    async stop() {}
    isRunning() { return true; }
    onNotification() { return disposable; }
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
        "visibleColumns": ["match", "kind", "semanticKind", "summary", "text", "location"],
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
      createStatusBarItem: () => ({ hide() {}, show() {} }),
      createOutputChannel: () => ({ clear() {}, append() {}, appendLine() {}, show() {}, dispose() {} }),
      registerWebviewViewProvider: () => disposable,
      createTreeView: () => disposable,
      onDidChangeActiveTextEditor: () => disposable,
    },
    languages: {
      createDiagnosticCollection: () => ({ ...disposable, delete() {}, set() {}, clear() {} }),
    },
    ConfigurationTarget: { Workspace: 2 },
    commands: { registerCommand: (name, callback) => { registered.set(name, callback); return disposable; } },
    MarkdownString: class MarkdownString {},
    RelativePattern: class RelativePattern { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    Uri: { file: (fsPath) => ({ fsPath, toString: () => `file://${fsPath}` }) },
  };

  const sample = {
    Samples: class Samples {
      constructor() { this.onDidChange = () => disposable; }
      defaultFlags() { return ["-DVALUE=a b", "-Iinclude path"]; }
    },
    SOURCE_EXTS: new Set([".cpp"]),
  };
  const results = Object.fromEntries(
    ["ResultStore", "Highlighter", "BindingsTree", "MatchesView"].map((name) => [
      name, class { constructor() {} },
    ]),
  );
  results.reveal = () => {};
  results.ResultStore = class {
    constructor() { this.generation = 2; this.result = { cwd: "/workspace", flags: ["-std=c++23"] }; }
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
