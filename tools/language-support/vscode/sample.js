// Which translation unit a .query file runs against, and with which flags.
//
// Precedence, highest first:
//   1. the sample picked for this query file (status bar / "Select Sample File")
//   2. a `# sample: <path> [flags…]` first line in the query file
//   3. the astmatcher.sample / astmatcher.flags settings
// A picked sample is remembered per query file in the workspace state.

const path = require("path");
const vscode = require("vscode");

const SOURCE_GLOB = "**/*.{c,cc,cpp,cxx,c++,m,mm,cu,h,hh,hpp,hxx}";
const EXCLUDE_GLOB = "**/{node_modules,build,.git,.cache}/**";
const SOURCE_LANGS = new Set(["c", "cpp", "objective-c", "objective-cpp", "cuda-cpp"]);
const SOURCE_EXTS = new Set([".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm", ".cu",
                             ".h", ".hh", ".hpp", ".hxx"]);

// Flags the lab uses for its non-C++ samples (see docs/part_11); anything else
// gets astmatcher.flags.
const FLAGS_BY_EXT = {
  ".m": ["-fobjc-exceptions"],
  ".mm": ["-fobjc-exceptions"],
  ".cu": ["-x", "cuda", "--cuda-host-only", "-nocudainc", "-nocudalib"],
  ".c": ["-std=c17"],
};

function config() {
  return vscode.workspace.getConfiguration("astmatcher");
}

class Samples {
  constructor(context) {
    this.state = context.workspaceState;
    this.changed = new vscode.EventEmitter();
    this.onDidChange = this.changed.event;
  }

  key(uri) {
    return `astmatcher.sample:${uri.toString()}`;
  }

  /** Folder that relative sample paths resolve against. */
  cwdFor(document) {
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    return folder ? folder.uri.fsPath : path.dirname(document.uri.fsPath);
  }

  /** { sample, flags, origin, absolute } for a query document. */
  resolve(document) {
    const cwd = this.cwdFor(document);
    const abs = (p) => (path.isAbsolute(p) ? p : path.join(cwd, p));
    const picked = this.state.get(this.key(document.uri));
    if (picked && picked.sample) {
      return { sample: picked.sample, flags: picked.flags || this.defaultFlags(picked.sample),
               origin: "picked", absolute: abs(picked.sample), cwd };
    }
    const first = document.lineCount ? document.lineAt(0).text : "";
    const match = /^#\s*sample:\s*(\S+)\s*(.*)$/.exec(first);
    if (match) {
      const flags = match[2].trim();
      return { sample: match[1], flags: flags ? flags.split(/\s+/) : config().get("flags"),
               origin: "# sample: line", absolute: abs(match[1]), cwd };
    }
    const sample = config().get("sample");
    return { sample, flags: config().get("flags"), origin: "settings",
             absolute: abs(sample), cwd };
  }

  defaultFlags(sample) {
    return FLAGS_BY_EXT[path.extname(sample).toLowerCase()] || config().get("flags");
  }

  async set(document, sample, flags) {
    await this.state.update(this.key(document.uri),
      sample ? { sample, flags: flags || this.defaultFlags(sample) } : undefined);
    this.changed.fire(document.uri);
  }

  /** Change the target while retaining flags configured for this query. */
  async setTarget(document, sample) {
    const current = this.resolve(document);
    return this.set(document, sample, current.flags);
  }

  /** Quick pick: open C/C++ editors first, then workspace sources, then Browse…. */
  async pick(document) {
    const current = this.resolve(document);
    const cwd = current.cwd;
    const rel = (fsPath) => path.relative(cwd, fsPath) || fsPath;

    const quick = vscode.window.createQuickPick();
    quick.title = `Sample for ${path.basename(document.uri.fsPath)}`;
    quick.placeholder = `Now: ${rel(current.absolute)} (${current.origin}) — type to filter`;
    quick.matchOnDescription = true;
    quick.busy = true;
    quick.show();

    const seen = new Set();
    const items = [];
    const add = (fsPath, detail) => {
      if (seen.has(fsPath)) return;
      seen.add(fsPath);
      items.push({ label: path.basename(fsPath), description: rel(path.dirname(fsPath)),
                   detail, fsPath });
    };
    const openEditors = vscode.window.visibleTextEditors
      .map((e) => e.document)
      .concat(vscode.workspace.textDocuments)
      .filter((d) => d.uri.scheme === "file" && SOURCE_LANGS.has(d.languageId));
    if (openEditors.length) {
      items.push({ label: "open editors", kind: vscode.QuickPickItemKind.Separator });
      openEditors.forEach((d) => add(d.uri.fsPath));
    }
    const actions = [
      { label: "$(folder-opened) Browse…", action: "browse" },
      { label: "$(discard) Reset to default", action: "reset",
        description: "use the # sample: line or the astmatcher.sample setting" },
    ];
    quick.items = [...actions, ...items];

    const files = await vscode.workspace.findFiles(SOURCE_GLOB, EXCLUDE_GLOB, 5000);
    files.sort((a, b) => a.fsPath.localeCompare(b.fsPath));
    if (files.length) {
      items.push({ label: "workspace", kind: vscode.QuickPickItemKind.Separator });
      files.forEach((f) => add(f.fsPath));
    }
    quick.items = [...actions, ...items];
    quick.busy = false;

    const choice = await new Promise((resolve) => {
      quick.onDidAccept(() => resolve(quick.selectedItems[0]));
      quick.onDidHide(() => resolve(undefined));
    });
    quick.dispose();
    if (!choice) return undefined;
    if (choice.action === "reset") {
      await this.set(document, undefined);
      return this.resolve(document);
    }
    let fsPath = choice.fsPath;
    if (choice.action === "browse") {
      const uris = await vscode.window.showOpenDialog({
        canSelectMany: false, defaultUri: vscode.Uri.file(cwd),
        filters: { "C / C++ / Objective-C / CUDA": ["c", "cc", "cpp", "cxx", "m", "mm", "cu",
                                                    "h", "hh", "hpp", "hxx"] },
      });
      if (!uris || !uris.length) return undefined;
      fsPath = uris[0].fsPath;
    }
    const stored = fsPath.startsWith(cwd + path.sep) ? path.relative(cwd, fsPath) : fsPath;
    await this.set(document, stored);
    return this.resolve(document);
  }

  async editFlags(document) {
    const current = this.resolve(document);
    const value = await vscode.window.showInputBox({
      title: `Compiler flags for ${path.basename(current.absolute)}`,
      prompt: "Passed after `--` to clang-query, separated by spaces",
      value: current.flags.join(" "),
    });
    if (value === undefined) return;
    await this.set(document, current.sample, value.trim() ? value.trim().split(/\s+/) : []);
  }
}

module.exports = { Samples, SOURCE_LANGS, SOURCE_EXTS };
