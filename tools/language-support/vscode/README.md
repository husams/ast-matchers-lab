# AST Matcher DSL for VS Code

Highlighting, completion, hover, signature help and diagnostics for
`clang-query` matcher scripts (`.query`, `.astmatcher`).

## Install

From the repository root on macOS with Homebrew:

```sh
brew install llvm grpc protobuf
cmake -S tools/language-support/native -B tools/language-support/native/build \
  -DCMAKE_PREFIX_PATH="$(brew --prefix llvm);$(brew --prefix grpc);$(brew --prefix protobuf)"
cmake --build tools/language-support/native/build --target astmatcher-native --parallel
cd tools/language-support/vscode
npm install
npx @vscode/vsce package
code --install-extension astmatcher-dsl-1.8.0.vsix
```

For development instead: open this folder in VS Code and press <kbd>F5</kbd>.

The extension finds the language server at
`tools/language-support/astmatcher-lsp/bin/astmatcher-lsp` inside the open
workspace. Set `astmatcher.server.path` if the lab lives elsewhere; with no
server the grammar and snippets still work (`astmatcher.server.enabled: false`
if you want only those).
**Run Query** also needs `astmatcher-native`, built from
[`../native/`](../native/) with CMake. Set `astmatcher.nativeServerPath` to
its executable when it is outside the installed tree or `PATH`. The Python
language server starts it over a private Unix socket and bridges its structured
gRPC reply into the result panel. A missing native executable is reported as a
run error.

Completion and syntax diagnostics also work before saving: select **AST Matcher
DSL** as the language of a new untitled editor. Matcher choices follow the
enclosing node type, including nested `anyOf(...)` and `fieldDecl(...)` calls.
Unexpected closing delimiters are underlined and listed in **Problems**.
Matcher suggestions open automatically while typing, including alongside
inline suggestions. Static snippets are hidden from completion so matcher
choices stay type filtered; use **Insert Snippet** when you want one explicitly.

## Colours

Four groups get their own colour in every theme: node matchers (teal, bold),
narrowing matchers / predicates (violet), traversal matchers (orange, italic)
and literals — strings, numbers, `true`/`false` (green). They come from the
server's `nodeMatcher` / `narrowingMatcher` / `traversalMatcher` / `literal`
semantic tokens, with matching TextMate rules for when the server is off.
Override them in your settings:

```jsonc
"editor.semanticTokenColorCustomizations": {
  "rules": { "traversalMatcher": { "foreground": "#FF8800" } }
}
```

## Running queries

<kbd>⌘↵</kbd> (<kbd>Ctrl↵</kbd>) runs the open `.query` file — unsaved edits
included — through the native Clang matcher server, and shows the result in
three places:

Both result views group nodes by source file, then by binding id, listing each
AST node once with the matches that bound it. The server assigns an opaque ID
to each bound AST node, so in

```
match cxxRecordDecl(hasName("Pair"),
  eachOf(has(fieldDecl(hasName("first")).bind("v")),
         has(fieldDecl(hasName("second")).bind("v")))).bind("d")
```

`d` is one record found by matches #1 and #2, and `v` is two fields:

```
▾ decls.cpp
  ▾ d — 1 node
      #1, #2  CXXRecordDecl  CXXRecordDecl  class Pair { int first; int second; }
  ▾ v — 2 nodes
      #1      FieldDecl      FieldDecl      int first
      #2      FieldDecl      FieldDecl      int second
```

The implicit `root`
binding is hidden unless a match binds nothing else; *Show root* (checkbox in the
panel, eye icon in the view title bars) brings it back.

- **AST Matches** (bottom panel, next to Output/Terminal): a tree-table — foldable
  rows for each source file, bind id, and node. Node columns are configurable:
  match, AST kind, declaration kind, summary, source text, and location. Click a header to
  sort, type in Filter to narrow; click a row (or <kbd>Enter</kbd>,
  <kbd>↑</kbd>/<kbd>↓</kbd>) to open the file and select exactly that node's text.
  Click a bind id (or press <kbd>Enter</kbd>) to select all its distinct matched
  regions in the source file; use the disclosure arrow to fold the group.
- **AST Match Bindings** (Explorer sidebar): the same file and bind-id groups
  with node selection actions.
- **Source files**: selecting a node or binding opens its source file and
  highlights its matched regions; enclosing nodes and other bindings are not included.

Matcher parse errors (e.g. `Matcher not found`) are shown in the panel and as
`astmatcher-native` diagnostics on the offending token in the query file.

### Choosing the file a query searches

The status bar shows the current sample while a `.query` editor is active
(`$(file-code) narrow_types.cpp`); click it — or run **AST Matcher: Select
Sample File…**, or the file icon in the editor title bar / panel — to pick from
open C/C++ editors, every C/C++/ObjC/CUDA file in the workspace, or *Browse…*.
Right-click a source file in the Explorer or editor → **Use as AST Matcher
Sample** does the same in one step. The pick is remembered per query file.

Precedence, highest first:

1. the sample picked for this query file (with flags suggested by extension:
   `.m` → `-fobjc-exceptions`, `.cu` → the lab's CUDA flags, `.c` → `-std=c17`,
   otherwise `astmatcher.flags`); change them with **Edit Compiler Flags…**
2. a first line `# sample: manifests/objc.m -fobjc-exceptions`
3. the `astmatcher.sample` / `astmatcher.flags` settings

*Reset to default* in the picker drops the per-file choice.

### From a source file

Right-click in a C/C++ editor or on the file in the Explorer → **AST Matcher**:

- **Run Query on This File…** — pick any `.query`/`.astmatcher` file in the
  workspace; it is pointed at this file and run (also the ▷ menu in the
  editor title bar).
- **New Query for This File** — creates `matchers/<name>.astmatcher`
  (`astmatcher.queriesDirectory`) with a `# sample:` line for this file and a
  starter `match`, and opens it.
- **Use as AST Matcher Sample** — makes it the sample of the last query file.

Explorer files and folders also offer **Run Query on This Target…** to select an
existing query, and **New Query and Run** to create a complete starter query and
run it immediately. The Matches toolbar can run the active query on a file, a
directory, or every workspace root; **Select Run Target…** stores the scope and
path so the current target stays visible in run settings.
For directory and workspace runs, matches appear as each file completes, with
a live scanned-file count; the final response reconciles the full result.

## Commands

| Command | Default key | What it does |
|---------|-------------|--------------|
| AST Matcher: Run Query | <kbd>⌘↵</kbd> / <kbd>Ctrl↵</kbd> | runs the query through the server; results in the panel, tree and editor |
| AST Matcher: Run Query in Terminal | <kbd>⇧⌘↵</kbd> / <kbd>Ctrl⇧↵</kbd> | saves and runs `clang-query -f <file> <sample> -- <flags>` in a terminal for hands-on lab work; this path supports file scope and compiler flags |
| AST Matcher: Select Sample File… | status bar | choose the translation unit for this query file |
| AST Matcher: Run Query on This Target… | — | from a C/C++ file or directory: pick a query and run it on that target |
| AST Matcher: New Query and Run | — | from a C/C++ file or directory: create a starter query and run it |
| AST Matcher: Edit Compiler Flags… | — | flags passed after `--` for this query file |
| AST Matcher: Run on File / Directory / Workspace | Matches toolbar | run the active query over the selected scope |
| AST Matcher: Select Run Target… | Matches toolbar | choose scope and its file, directory, or workspace root |
| AST Matcher: Run Settings… | Matches toolbar | edit run options in the Matches panel |
| AST Matcher: Clear Results | — | empties the panel, tree and highlights |
| AST Matcher: Restart Language Server | — | after editing the server or regenerating `data/` |

The explicit terminal command finds `clang-query` under `$LLVM/bin`, then on
`PATH`. **Run Query** uses the native server and does not fall back to that command.

## Settings

| Setting | Default |
|---------|---------|
| `astmatcher.server.enabled` | `true` |
| `astmatcher.server.path` | `""` (auto-detect in the workspace) |
| `astmatcher.server.python` | `python3` |
| `astmatcher.nativeServerPath` | `""` (installed or in-tree binary, then `PATH`) |
| `astmatcher.sample` | `manifests/intro.cpp` |
| `astmatcher.flags` | `["-std=c++23"]` |
| `astmatcher.scope` | `"file"` |
| `astmatcher.targetPath` | selected file or directory; workspace scope searches all workspace folders |
| `astmatcher.compileCommands` | `"auto"` (nearest `compile_commands.json` at or above the file, also under `build/` or `out/`; `""` turns it off) |
| `astmatcher.traversal` | `"AsIs"` |
| `astmatcher.exclusions` | `[]` |
| `astmatcher.visibleColumns` | match, kind, semantic kind, summary, text, location |
| `astmatcher.cacheEnabled` | `false` |
| `astmatcher.cacheLocation` | extension global storage `cache/` |
