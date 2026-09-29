# Language support for the AST Matcher DSL

Syntax highlighting and autocomplete for the matcher language you type into
`clang-query` — the same DSL this lab teaches. Three editor front ends share
the generated matcher catalog, and native C++ executes queries:

| Target | What you get | Needs |
|--------|--------------|-------|
| [`vscode/`](vscode/) | grammar, snippets, and the full language server | VS Code 1.82+, `npm install` |
| [`astmatcher-lsp/`](astmatcher-lsp/) | editor-agnostic LSP server + batch checker | Python 3.10+, nothing else |
| [`vim/`](vim/) | syntax file, ftdetect/ftplugin, dictionary completion | Vim 8 or Neovim |
| [`native/`](native/) | Clang matcher engine and gRPC server on a Unix socket | CMake, Clang/LLVM development files, Protobuf, gRPC |

Everything is generated from `scripts/catalog.json` (all 726 AST Matcher
Reference rows) plus the real clang class hierarchies read out of the Homebrew
LLVM headers, so the matcher list, the types, and the enum values match the
`clang-query 22` you run the lab against.

## Quick start

```sh
cd ast-matchers-lab

# 1. type-check a query from the shell (no editor involved)
tools/language-support/astmatcher-lsp/bin/astmatcher-lsp --check manifests/queries/*.query

# 2. vim / neovim
#    (or copy the four directories into ~/.vim, or point your plugin manager here)
echo 'set runtimepath+=~/workspace/qemu-vms/ast-matchers-lab/tools/language-support/vim' \
  >> ~/.vimrc

# 3. build the native query server on macOS with Homebrew
brew install llvm grpc protobuf
cmake -S tools/language-support/native -B tools/language-support/native/build \
  -DCMAKE_PREFIX_PATH="$(brew --prefix llvm);$(brew --prefix grpc);$(brew --prefix protobuf)"
cmake --build tools/language-support/native/build --parallel

# 4. VS Code
cd tools/language-support/vscode && npm install && npx @vscode/vsce package
code --install-extension astmatcher-dsl-1.9.0.vsix
```

`astmatcher-lsp --run` and VS Code **Run Query** send each translation unit to
`astmatcher-native`. The Python language server remains standard-library-only:
it starts the native server on a private Unix socket, sends a protobuf JSON
request to the native CLI bridge, and maps the structured gRPC reply into the
existing results panel. Set `astmatcher.nativeServerPath` or
`ASTMATCHER_NATIVE` when the native binary is outside the in-tree build,
installed sibling directory, or `PATH`. A missing native binary is an error;
query execution never silently switches to `clang-query`.

On RHEL/Rocky/Alma 9, run the installer from the repository with no options:

```sh
tools/language-support/deploy-rhel.sh
```

The installer defaults to `~/.local/astmatcher`, enables the build
repositories, installs dependencies, builds and tests the native and Python
servers, and verifies a real gRPC query through the installed binaries. On
Rocky/Alma it enables CRB and EPEL. On RHEL it first uses installed packages
or configured repositories, including RHUI or private mirrors, and enables
EPEL and CodeReady Builder only if dependencies are missing. If no repository
can supply them, register RHEL or configure a mirror. Installing missing
packages needs sudo (or root) and network access.
If VS Code is present, it also builds and installs the extension and sets its
user settings. On a headless host it installs only the native and Python
servers; rerun the same command after installing VS Code to add the extension.
Use `--prefix DIR`, `--server-only`, or `--skip-tests` to customize that
behavior. `--prefix` also installs dependencies; use `--skip-deps` when the
host already has them.

The installer builds against the selected LLVM 21 or newer. Use
`--llvm /path/to/llvm` for a separate LLVM installation. The checked-in editor
catalog and lab examples target LLVM 22; on LLVM 21, the installer generates
data from local headers and filters suggestions against the linked Clang
registry in a build directory, preserving the checked-in LLVM 22 files. It
also replaces generated snippets and syntax in the installed VSIX. Pass
`--vsix /path/to/astmatcher-dsl.vsix` to install a prebuilt extension on a VS
Code host without Node.js.

## What the editor knows

* **Type-aware completion.** Inside `functionDecl(` it offers `hasName`,
  `isDefinition`, `hasParameter` — not `hasCastKind`, which needs a
  `CastExpr`. Inside `hasBody(` it offers statements. The matchers that apply
  to the *exact* node come first, then the ones inherited from its bases, then
  the node matchers, then `allOf`/`anyOf`/`unless`.
* **String arguments that have a fixed vocabulary**: `hasAttr("attr::…")` (453
  attributes), `hasCastKind("CK_…")` (70 cast kinds), `hasOperatorName("…")`,
  `ofKind("UETT_…")`, and the ids you bound with `.bind()` earlier in the same
  match, for `equalsBoundNode()`.
* **Commands and settings**: `match`, `let`, `set traversal AsIs`,
  `set output detailed-ast`, `enable output print`, `.bind("id")`,
  `mapAnyOf(…).with(…)`.
* **Hover** shows every overload's signature, the reference documentation for
  the matcher, and a link to the lab part that teaches it.
* **Diagnostics** reproduce what `clang-query` would tell you, before you run
  it:

  ```
  match functionDecl(integerLiteral())
    Incorrect type for arg 1. (Expected = Matcher<FunctionDecl>) != (Actual = Matcher<Stmt>)

  match hasName("x")
    Not a valid top-level matcher: `hasName` narrows a node instead of naming one

  match functionDecl(hasAttr("attr::Ovrride"))
    Unknown value 'attr::Ovrride' for arg 1; did you mean 'attr::Override'
  ```

  Plus two things `clang-query` itself will not tell you: a matcher that is in
  the reference but **not registered in clang-query 22** (the 14 names listed
  in `CLAUDE.md`), and an argument that *builds* but can never match because
  the node kinds are siblings (`functionDecl(varDecl())`).

## Query results and record explorer

**Run Query** shows bound nodes in **AST Matches** and **AST Match Bindings**.
The default results table emphasizes each entity: a qualified callable signature,
a record name and kind, or a declaration name and type when available. Binding,
AST kind, and location remain visible. Expand **Source** in an entity cell when
you need the matched text; selecting a result still highlights its source.

Choose **Explore Record** on a record result, in the bindings tree, or at a
class/struct/union in a C/C++ editor. A full editor tab shows a class diagram:
records are cards, fields and methods appear inside their record, and lines
connect inheritance, record-typed fields, and class template relationships.
An instantiated class links to the template pattern it uses; a specialization
links to the template it specializes. Select a class or relationship for
details and source evidence, then reveal a related class to inspect more of its
neighborhood. Filter bases, known derived classes, template links, field types,
and known incoming field links from the selected class. Use **Open source**,
zoom, pan, and Fit to navigate. The explorer inspects the selected translation
unit with its compile options; it does not build a workspace-wide derived-class index or
infer field ownership from a type alone. Unavailable definitions and bounded
graphs are identified in the view.

## Layout

```
tools/language-support/
├── generate.py            catalog.json + clang headers -> data/ and the two grammars
├── check.sh               data in sync + unit tests + corpus check
├── corpus_check.py        runs the analyzer over every verified example in the lab
├── data/
│   ├── matchers.json      516 names, 726 overloads, params, docs, part numbers
│   ├── hierarchy.json     536 AST classes -> base class
│   └── enums.json         cast kinds, attributes, operators, settings
├── astmatcher-lsp/        the language server (stdlib-only Python)
├── native/                C++ Clang matcher engine and Unix socket gRPC server
├── vscode/                extension: grammar, snippets, LSP client, run command
└── vim/                   syntax, ftdetect, ftplugin, autoload, dictionary
```

## Regenerating

The data files are committed, so day-to-day use needs no LLVM headers. Rerun
the generator after a `brew` LLVM major bump or any edit to
`scripts/catalog.json` — the same moment `CLAUDE.md` tells you to rerun
`scripts/check.sh`:

```sh
export LLVM=$(brew --prefix llvm)
python3 tools/language-support/generate.py     # rewrites data/, the grammar, the vim syntax
tools/language-support/check.sh                # unit tests + verified examples
```

`generate.py --check` regenerates into a temp directory and diffs, for CI.

## How the type checking works

`clang-query`'s registry converts a `Matcher<A>` to a `Matcher<B>` when A and B
are related in *either* direction, which is why `functionDecl(isPublic())`
(base) and `decl(functionDecl())` (derived) both work, while
`functionDecl(integerLiteral())` does not. The server reproduces that rule with
the real hierarchy from `DeclNodes.inc`, `StmtNodes.inc`, `TypeNodes.inc` and
`TypeLocNodes.def`, plus the two special cases clang bakes in: `QualType` and
`Type` interconvert, and `hasDeclaration` accepts any node with a `getDecl()`.

Every rule in `analyze.py` was checked against the real tool, and
`corpus_check.py` keeps it honest: the lab's 997 verified examples must produce
zero errors.
