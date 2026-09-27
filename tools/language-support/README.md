# Language support for the AST Matcher DSL

Syntax highlighting and autocomplete for the matcher language you type into
`clang-query` — the same DSL this lab teaches. Three front ends over one
source of truth:

| Target | What you get | Needs |
|--------|--------------|-------|
| [`vscode/`](vscode/) | grammar, snippets, and the full language server | VS Code 1.82+, `npm install` |
| [`astmatcher-lsp/`](astmatcher-lsp/) | editor-agnostic LSP server + batch checker | Python 3.10+, nothing else |
| [`vim/`](vim/) | syntax file, ftdetect/ftplugin, dictionary completion | Vim 8 or Neovim |

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

# 3. VS Code
cd tools/language-support/vscode && npm install && npx @vscode/vsce package
code --install-extension astmatcher-dsl-1.0.0.vsix
```

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
tools/language-support/check.sh                # 46 tests + 997 verified examples
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
