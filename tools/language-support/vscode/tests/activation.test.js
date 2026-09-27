"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

test("activation starts the language client for saved and untitled matcher documents", async () => {
  let clientOptions;
  let started = false;

  class LanguageClient {
    constructor(_id, _name, _serverOptions, options) { clientOptions = options; }
    async start() { started = true; }
    async stop() {}
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
      getConfiguration: () => ({ get: (key) => ({
        "server.enabled": true,
        "server.path": path.resolve(__dirname, "../../astmatcher-lsp/bin/astmatcher-lsp"),
        "server.python": "python3",
      })[key] }),
      getWorkspaceFolder: () => undefined,
      onDidChangeTextDocument: () => disposable,
      onDidChangeConfiguration: () => disposable,
    },
    window: {
      activeTextEditor: undefined,
      createStatusBarItem: () => ({ hide() {}, show() {} }),
      registerWebviewViewProvider: () => disposable,
      createTreeView: () => disposable,
      onDidChangeActiveTextEditor: () => disposable,
    },
    languages: {
      createDiagnosticCollection: () => ({ ...disposable, delete() {}, set() {}, clear() {} }),
    },
    commands: { registerCommand: () => disposable },
    MarkdownString: class MarkdownString {},
  };

  const sample = {
    Samples: class Samples {
      constructor() { this.onDidChange = () => disposable; }
    },
    SOURCE_EXTS: new Set(),
  };
  const results = Object.fromEntries(
    ["ResultStore", "Highlighter", "BindingsTree", "MatchesView"].map((name) => [
      name, class { constructor() {} },
    ]),
  );
  results.reveal = () => {};

  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === "vscode") return vscode;
    if (request === "vscode-languageclient/node") {
      return { LanguageClient, TransportKind: { stdio: 1 } };
    }
    if (request === "./sample") return sample;
    if (request === "./results") return results;
    return originalLoad.call(this, request, parent, isMain);
  };

  try {
    const extensionPath = require.resolve("../extension");
    delete require.cache[extensionPath];
    const extension = require("../extension");
    await extension.activate({ subscriptions: [], workspaceState: {} });

    const selector = clientOptions.documentSelector;
    const matches = (scheme, language) => selector.some((entry) =>
      entry.scheme === scheme && entry.language === language);
    assert.equal(matches("file", "astmatcher"), true);
    assert.equal(matches("untitled", "astmatcher"), true);
    assert.equal(matches("file", "cpp"), false);
    assert.equal(matches("untitled", "plaintext"), false);
    assert.equal(started, true);
    await extension.deactivate();
  } finally {
    Module._load = originalLoad;
    delete require.cache[require.resolve("../extension")];
  }
});
