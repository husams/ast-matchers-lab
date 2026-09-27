// VS Code client for the AST matcher DSL.
//
// The grammar and snippets work on their own; this file adds the language
// server (completion, hover, signature help, diagnostics, semantic tokens) and
// a command that runs the open .query file through clang-query.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client;
let terminal;

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
    documentSelector: [{ scheme: "file", language: "astmatcher" }],
    outputChannelName: "AST Matcher DSL",
  };
  client = new LanguageClient("astmatcher", "AST Matcher DSL", serverOptions, clientOptions);
  context.subscriptions.push(client);
  await client.start();
}

/** `# sample: manifests/objc.m -fobjc-exceptions` overrides the settings. */
function sampleFor(document) {
  const first = document.lineAt(0).text;
  const match = /^#\s*sample:\s*(\S+)\s*(.*)$/.exec(first);
  if (match) {
    const flags = match[2].trim();
    return { sample: match[1], flags: flags ? flags.split(/\s+/) : config().get("flags") };
  }
  return { sample: config().get("sample"), flags: config().get("flags") };
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

async function runQuery() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "astmatcher") {
    return;
  }
  await editor.document.save();
  const { sample, flags } = sampleFor(editor.document);
  const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
  const cwd = folder ? folder.uri.fsPath : path.dirname(editor.document.uri.fsPath);

  if (!terminal || terminal.exitStatus) {
    terminal = vscode.window.createTerminal({ name: "clang-query", cwd });
  }
  const parts = [
    quote(clangQuery()), "-f", quote(editor.document.uri.fsPath), quote(sample),
    "--", ...flags.map(quote),
  ];
  terminal.show(true);
  terminal.sendText(parts.join(" "));
}

/** Single-quote anything that is not plainly safe: the text goes to a shell. */
function quote(value) {
  return /^[\w@%+=:,.\/-]+$/.test(value) ? value : `'${value.replace(/'/g, "'\\''")}'`;
}

async function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("astmatcher.runQuery", runQuery),
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
