# AST Matcher DSL for VS Code

Highlighting, completion, hover, signature help and diagnostics for
`clang-query` matcher scripts (`.query`, `.astmatcher`).

## Install

```sh
cd tools/language-support/vscode
npm install
npx @vscode/vsce package
code --install-extension astmatcher-dsl-1.5.4.vsix
```

For development instead: open this folder in VS Code and press <kbd>F5</kbd>.

The extension finds the language server at
`tools/language-support/astmatcher-lsp/bin/astmatcher-lsp` inside the open
workspace. Set `astmatcher.server.path` if the lab lives elsewhere; with no
server the grammar and snippets still work (`astmatcher.server.enabled: false`
if you want only those).

Completion and syntax diagnostics also work before saving: select **AST Matcher
DSL** as the language of a new untitled editor. Matcher choices follow the
enclosing node type, including nested `anyOf(...)` and `fieldDecl(...)` calls.
Unexpected closing delimiters are underlined and listed in **Problems**.
Matcher suggestions open automatically while typing, including alongside
inline suggestions. Static snippets are hidden from completion so matcher
choices stay type filtered; use **Insert Snippet** when you want one explicitly.

## Running queries

<kbd>⌘↵</kbd> (<kbd>Ctrl↵</kbd>) runs the open `.query` file — unsaved edits
included — through clang-query via the language server, and shows the result in
three places:

Both views are grouped **by bind id**, listing every AST node once with the
matches that bound it. The server tells nodes apart by their AST address, so in

```
match cxxRecordDecl(hasName("Pair"),
  eachOf(has(fieldDecl(hasName("first")).bind("v")),
         has(fieldDecl(hasName("second")).bind("v")))).bind("d")
```

`d` is one record found by matches #1 and #2, and `v` is two fields:

```
▾ d — 1 node
  └─ #1, #2  CXXRecordDecl  class Pair { int first; int second; }
▾ v — 2 nodes
  ├─ #1      FieldDecl      int first
  └─ #2      FieldDecl      int second
```

clang-query's implicit `root`
binding is hidden unless a match binds nothing else; *Show root* (checkbox in the
panel, eye icon in the view title bars) brings it back.

- **AST Matches** (bottom panel, next to Output/Terminal): a tree-table — a
  foldable row per bind id (▾ `d`, ▾ `v`) with its nodes under it (`├─ #1`,
  `└─ #2`) and the columns Kind, Summary, Source, Location. Click a header to
  sort, type in Filter to narrow; click a row (or <kbd>Enter</kbd>,
  <kbd>↑</kbd>/<kbd>↓</kbd>) to open the file and select exactly that node's text.
  Click a bind id (or press <kbd>Enter</kbd>) to select all its distinct matched
  regions in the source file; use the disclosure arrow to fold the group.
- **AST Match Bindings** (Explorer sidebar): the same groups and selection
  actions as an outline.
- **The sample file**: only the selected node or binding's matched regions are
  highlighted, with separate text selections for distinct ranges; enclosing
  nodes and other bindings are not included.

clang-query errors (e.g. `Matcher not found`) are shown in the panel and as
`clang-query` diagnostics on the offending token in the query file.

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

## Commands

| Command | Default key | What it does |
|---------|-------------|--------------|
| AST Matcher: Run Query | <kbd>⌘↵</kbd> / <kbd>Ctrl↵</kbd> | runs the query through the server; results in the panel, tree and editor |
| AST Matcher: Run Query in Terminal | <kbd>⇧⌘↵</kbd> / <kbd>Ctrl⇧↵</kbd> | saves and runs `clang-query -f <file> <sample> -- <flags>` in a terminal (also the fallback when the server is off) |
| AST Matcher: Select Sample File… | status bar | choose the translation unit for this query file |
| AST Matcher: Run Query on This File… | — | from a C/C++ file: pick a query and run it on that file |
| AST Matcher: New Query for This File | — | from a C/C++ file: create and open a query aimed at it |
| AST Matcher: Edit Compiler Flags… | — | flags passed after `--` for this query file |
| AST Matcher: Clear Results | — | empties the panel, tree and highlights |
| AST Matcher: Restart Language Server | — | after editing the server or regenerating `data/` |

`astmatcher.clangQueryPath` defaults to `$LLVM/bin/clang-query`, else
`clang-query` on `PATH`.

## Settings

| Setting | Default |
|---------|---------|
| `astmatcher.server.enabled` | `true` |
| `astmatcher.server.path` | `""` (auto-detect in the workspace) |
| `astmatcher.server.python` | `python3` |
| `astmatcher.clangQueryPath` | `""` (`$LLVM/bin/clang-query`) |
| `astmatcher.sample` | `manifests/intro.cpp` |
| `astmatcher.flags` | `["-std=c++23"]` |
