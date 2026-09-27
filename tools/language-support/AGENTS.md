# Language Support for the AST Matcher DSL — Agent Guide

Editor tooling for the matcher language typed into `clang-query`. It belongs to
the **AST Matchers Lab** (`ast-matchers-lab/`, see `../../AGENTS.md`), which
teaches that DSL, and it is built from the lab's own data: `scripts/catalog.json`
(all 726 AST Matcher Reference rows) plus the class hierarchies and enums read
from the Homebrew LLVM 22 headers. It is optional for the lab and
self-contained: nothing in `docs/`, `manifests/` or `scripts/` depends on it.

Three editor front ends share one source of truth; a native C++ service runs queries:

| Part | What it is | Runtime |
|------|------------|---------|
| `astmatcher-lsp/` | LSP server, batch checker (`--check`), native query bridge (`--run`) | Python 3.10+, stdlib only |
| `native/` | Clang matcher engine and gRPC server over a Unix socket | CMake, Clang/LLVM, Protobuf, gRPC |
| `vscode/` | VS Code extension: grammar, snippets, LSP client, matches panel, bindings outline | VS Code 1.82+, `vscode-languageclient` |
| `vim/` | syntax, ftdetect, ftplugin, autoload (`:AstMatcherCheck`, omnifunc), dictionary | Vim 8 / Neovim |

## Layout

```
tools/language-support/
├── AGENTS.md               ← this file
├── README.md               ← user-facing overview
├── generate.py             ← catalog.json + LLVM headers -> data/ + grammars (GENERATED outputs)
├── check.sh                ← data in sync + unit tests + corpus check (run before finishing)
├── corpus_check.py         ← analyzer over every verified lab example: 0 errors allowed
├── data/                   ← GENERATED: matchers.json, hierarchy.json, enums.json
├── astmatcher-lsp/
│   ├── bin/astmatcher-lsp  ← launcher (sets PYTHONPATH, honours ASTMATCHER_PYTHON)
│   ├── astmatcher_lsp/
│   │   ├── catalog.py      ← loads data/, "is kind A related to B", overload distance
│   │   ├── lexer.py        ← tokens, offset <-> (line, character)
│   │   ├── parser.py       ← error-tolerant tree (half-typed input must parse)
│   │   ├── analyze.py      ← overload resolution + diagnostics worded like clang-query
│   │   ├── features.py     ← completion, hover, signature help, semantic tokens
│   │   ├── run.py          ← discovers sources, calls native bridge, builds LSP result JSON
│   │   ├── server.py       ← JSON-RPC loop; `astmatcher/runQuery` on a worker thread
│   │   └── cli.py          ← --stdio / --check / --complete / --hover / --signature / --run
│   └── tests/test_language.py
├── native/                ← C++ matcher engine, protobuf schema, gRPC server and CLI bridge
├── vscode/
│   ├── extension.js        ← activation, commands, LSP client, runQuery wiring
│   ├── sample.js           ← which source file a query runs against (per-file pick)
│   ├── results.js          ← result store, bindings outline, editor highlights, panel host
│   ├── media/matches.{js,css} ← the "AST Matches" webview (tree-table)
│   ├── syntaxes/, snippets/   ← GENERATED
│   └── package.json        ← contributions; bump "version" on every change
└── vim/                    ← syntax/ is GENERATED; the rest is hand-written
```

## How it works

**Static analysis.** `parser.py` builds a loose tree of `match` / `let` /
`set` commands. `analyze.py` resolves each call against `catalog.py`: every
distinct overload shape is tried and the cleanest wins (memoized per
`(call, expected kind)` — without the cache checking is exponential in nesting
depth). Diagnostics deliberately reuse clang-query's wording ("Matcher not
found: x", "Incorrect type for arg 1. (Expected = …) != (Actual = …)").
Completion is filtered by the node kind the argument slot expects.

**Semantic tokens.** Custom types `nodeMatcher`, `narrowingMatcher`,
`traversalMatcher`, `literal` (super types class/function/method/string). The
extension colours them via `configurationDefaults`, with matching TextMate
rules for when the server is off.

**Running queries** (`run.py`, request `astmatcher/runQuery`, CLI `--run`).
The Python process keeps LSP, query text, source discovery, compilation database
and cache behavior. It starts `astmatcher-native` on a private Unix socket and
sends structured requests through the native CLI's gRPC bridge. The native
service uses Clang's matcher parser and AST directly and returns protobuf JSON
with queries, bindings, diagnostics and source ranges. `run.py` maps this
reply to the established LSP result JSON. No query execution parses
`clang-query` output or falls back to launching `clang-query`.

The result has two views of the same data: `queries` (clang-query's
match-by-match order) and `bindings` (`{id: [node…]}`, each AST node once with
the matches that bound it — nodes have opaque native IDs, so the
outer `.bind("d")` of an `eachOf(...)` is one node found by several matches).
Full schema: module docstring of `run.py` and `astmatcher-lsp/README.md`.

**VS Code UI.** ⌘↵ runs the open query through the server. The **AST Matches**
panel (bottom) and the **AST Match Bindings** outline (Explorer) both show
`bindings` grouped by id (`▾ d` → `└─ #1, #2`, `▾ v` → `├─ #1`, `└─ #2`);
clang-query's implicit `root` is hidden unless nothing else is bound or
*Show root* is on. Clicking a node opens the file as a tab (never a split) and
selects exactly its range; clicking a bind id selects all its distinct matched
ranges. Only the selected node or binding is highlighted; disclosure arrows
fold groups independently. The sample file is chosen per query file
(status bar, *Select Sample File…*, or right-click a C/C++ file → *AST
Matcher*); precedence: per-file pick > `# sample:` first line > settings.

## Working on it

```sh
cd ast-matchers-lab
tools/language-support/check.sh                   # must pass before finishing
python3 -m unittest discover -s tools/language-support/astmatcher-lsp/tests
tools/language-support/astmatcher-lsp/bin/astmatcher-lsp --check manifests/queries/*.query
tools/language-support/astmatcher-lsp/bin/astmatcher-lsp \
    --run manifests/queries/use-nullptr.query --sample manifests/capstone.cpp -- -std=c++23
cmake -S tools/language-support/native -B tools/language-support/native/build
cmake --build tools/language-support/native/build --parallel
```

Rules:

- **Never hand-edit generated files** (`data/`, `vscode/syntaxes/`,
  `vscode/snippets/`, `vim/syntax/`, `vim/dict/`). Change `generate.py` and run
  `python3 tools/language-support/generate.py`. Regenerate after any change to
  `scripts/catalog.json` and after a brew LLVM major bump.
- **No false positives on the lab.** `corpus_check.py` runs the analyzer over
  every ```` ```clang-query ```` block in `docs/` and every `manifests/**/*.query`;
  those are verified against clang-query 22, so any *error* there is a server
  bug. Warnings are allowed.
- **Match the DSL, don't guess.** When changing analysis or native execution,
  compare behavior with the real `clang-query` binary and test the native
  server's structured response; `clang-query` is a reference tool for the lab,
  not a runtime dependency of Run Query.
- **Server stays stdlib-only** Python 3.10+; no pip dependencies.
- **The `runQuery` JSON is a contract** between the Python bridge and
  `vscode/results.js` / `media/matches.js`; change both sides together and
  update the schema in `astmatcher-lsp/README.md`. The native wire contract is
  `native/proto/astmatcher.proto`.
- **Webview**: theme colours only via `var(--vscode-…)`; scripts load with a
  nonce under a strict CSP; no inline handlers.
- Commands that run on a query file from a panel use the last active query
  editor (`queryDocument()`), since focus is in the panel.

## Installing locally (this machine)

The extension is installed from a `.vsix`, never published:

```sh
cd tools/language-support/vscode
# bump "version" in package.json first
npm install && npx @vscode/vsce package --allow-missing-repository
code --install-extension astmatcher-dsl-<version>.vsix --force
```

The server is installed as a copy, not a link, so re-sync it after changing
`astmatcher_lsp/`:

```sh
cmake -S tools/language-support/native -B tools/language-support/native/build \
  -DCMAKE_PREFIX_PATH="$(brew --prefix llvm);$(brew --prefix grpc);$(brew --prefix protobuf)"
cmake --build tools/language-support/native/build --target astmatcher-native --parallel
install -m 0755 tools/language-support/native/build/astmatcher-native ~/.local/bin/astmatcher-native
rsync -a --delete --exclude __pycache__ \
  tools/language-support/astmatcher-lsp/astmatcher_lsp ~/.local/share/astmatcher-lsp/
cp tools/language-support/data/*.json ~/.local/share/astmatcher-lsp/data/
```

`~/.local/bin/astmatcher-lsp` is a wrapper that sets `PYTHONPATH` and
`ASTMATCHER_DATA` to `~/.local/share/astmatcher-lsp`. VS Code user settings
point at it: `astmatcher.server.path`, `astmatcher.nativeServerPath`,
`astmatcher.sample`, `astmatcher.flags`. The wrapper should also set
`ASTMATCHER_NATIVE` to the installed `astmatcher-native` executable. After
changing server code, tell the user to reload the
window (or run *AST Matcher: Restart Language Server*).

For RHEL/Rocky/Alma 9, run `tools/language-support/deploy-rhel.sh` with no
options. It installs the native and Python servers under
`~/.local/astmatcher`, installs dependencies, and adds the VS Code extension
when VS Code is present. See `README.md` for prerequisites and overrides.

## Known limits

- 14 reference matchers are not registered in clang-query 22 (listed in the lab
  `AGENTS.md`); the analyzer warns on them instead of erroring.
- Native bindings use Clang source locations; locationless types
  (`qualType().bind(...)`) have no source range.
- Positions use Python string indices; characters outside the BMP in a query
  file can shift LSP columns.
