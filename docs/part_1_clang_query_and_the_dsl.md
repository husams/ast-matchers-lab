# Part 1 — clang-query & the DSL Grammar

[← README](README.md) | [Part 2 — Node Matchers I — Declarations →](part_2_node_matchers_decls.md)

**Sample:** `manifests/intro.cpp` · flags: `-std=c++23`

## What You'll Learn
- Why Clang has a *declarative* matcher language at all, and how clang-tidy is built on it.
- How to start `clang-query`, pass compiler flags after `--`, script it with `-c` and `-f`.
- The three matcher categories the reference uses (node / narrowing / traversal) and the typing rules that make a matcher expression legal.
- How to read match output, bind nodes, and switch between `print`, `diag` and `dump` views.
- `let`, query files, and the two traversal modes (`AsIs` vs `IgnoreUnlessSpelledInSource`).
- How to read one entry of the LibASTMatchers Reference — the format every later part of this lab mirrors.

## The Big Picture

Clang turns a translation unit into an **AST**: a tree whose nodes are declarations (`FunctionDecl`, `FieldDecl`, …), statements and expressions (`ReturnStmt`, `CallExpr`, …), types and a few other kinds. Any tool that wants to find "all functions that return a literal" has two options:

1. **Imperative** — write a visitor that walks every node, keeps state, and checks conditions by hand.
2. **Declarative** — describe the *shape* of the node you want and let a library find it.

The AST Matcher DSL is option 2. A matcher is a nested expression that reads like the tree it describes:

```text
functionDecl(                       <- node matcher: "I am a FunctionDecl"
  hasName("total"),                 <- narrowing: filter by a property
  hasDescendant(                    <- traversal: jump to a related node
    integerLiteral(equals(3))))     <- node + narrowing again, one level down
```

`clang-query` is a REPL around that library: load a source file, type a matcher, see what it matches. It is the fastest way to learn the vocabulary, because every guess is answered in under a second and the answer is printed as source lines.

Start a session for this part:

```bash
export LLVM=$(brew --prefix llvm)
$LLVM/bin/clang-query manifests/intro.cpp -- -std=c++23
```

Keep `manifests/intro.cpp` open next to the session — most **Expected** lines cite its line numbers.

---

## 1.1 — Why a matcher DSL

A hand-written `RecursiveASTVisitor` for "functions whose body contains `a + b`" needs a class, two or three `Visit*` overrides, and a flag that remembers which function you are inside. The matcher version is one expression:

```text
functionDecl(hasDescendant(binaryOperator(hasOperatorName("+"))))
```

That difference is the whole reason the DSL exists. Three consequences follow:

- **clang-tidy is a matcher collection.** Nearly every check registers one or more matchers and a callback; the callback only runs on the matched node. Learning the DSL is learning how clang-tidy thinks.
- **The reference is the vocabulary.** https://clang.llvm.org/docs/LibASTMatchersReference.html lists every matcher in three tables (node, narrowing, traversal). It is complete but terse, and it gives no way to try anything.
- **This lab walks all of it.** Parts 2–11 take every row of that reference, one entry each, and turn the "Given … matches …" prose into a `clang-query` command you can run. Part 1 teaches the tool and the grammar so those entries make sense.

## 1.2 — Starting clang-query

`clang-query` is a Clang *tool*, so it takes the same command line as every other LibTooling program: source files first, then `--`, then the compiler flags you would pass to `clang`. Without a `--` (or a `compile_commands.json` next to the file) it refuses to guess and prints `Could not auto-detect compilation database`.

```bash
$LLVM/bin/clang-query manifests/intro.cpp -- -std=c++23
```

Three ways to feed it commands:

| Form | What it does |
|------|--------------|
| interactive prompt `clang-query>` | Type one command per line; `quit` (or `q`) leaves. |
| `-c 'command'` (repeatable) | Run commands non-interactively; multi-line commands are fine inside the quotes. |
| `-f file.query` | Run a script, one command per line, `#` starts a comment. |

At the prompt, `help` prints the complete command list (it takes no argument — `help match` is an error). The commands are: `match`/`m`, `let`/`l`, `set bind-root`, `set print-matcher`, `set enable-profile`, `set traversal`, `set output`, `enable output`, `disable output`, `quit`/`q`. That is the entire surface; everything else you type is a matcher.

Your first match. `functionDecl` says "a function declaration", `hasName` narrows it to one name:

```clang-query
match functionDecl(hasName("add"))
```

**Expected:** 1 match — `add` at `intro.cpp:3`.

`m` is a synonym for `match`:

```clang-query
m functionDecl(hasName("twice"))
```

**Expected:** 1 match — `twice` at `intro.cpp:4`.

The same command from a shell, using `-c`. Because `-c` is repeatable, `set`/`let` lines can precede the `match` in the same invocation:

```bash
$LLVM/bin/clang-query -c 'match functionDecl(hasName("add"))' manifests/intro.cpp -- -std=c++23
```

## 1.3 — The three matcher categories

The reference sorts every matcher into exactly one of three tables. The categories are not decoration: they decide **where in an expression a matcher may appear**.

| Category | Job | Where it may appear | Examples |
|----------|-----|---------------------|----------|
| **Node matcher** | "The node is of this kind." | The **only** thing allowed outermost; also anywhere a node is expected. | `functionDecl()`, `cxxRecordDecl()`, `integerLiteral()`, `stmt()` |
| **Narrowing matcher** | Filter the *current* node by a property. | Only *inside* a node matcher. | `hasName("x")`, `isDefinition()`, `equals(42)`, `parameterCountIs(2)` |
| **Traversal matcher** | Jump to a *related* node and match that. | Only inside a node matcher; its argument is another matcher. | `has(…)`, `hasDescendant(…)`, `hasType(…)`, `callee(…)` |

Read a matcher expression **outside-in**: each node matcher opens a "frame" that says which node kind you are standing on; narrowing matchers test that node; traversal matchers move the frame somewhere else and the nesting starts again.

```text
   functionDecl( hasName("total") , hasDescendant( integerLiteral( equals(3) ) ) )
   ^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^  ^^^^^^^^^^^^^^  ^^^^^^^^^
   node          narrowing          traversal      node            narrowing
   |-- frame: FunctionDecl ------------------------|-- frame: IntegerLiteral --|
```

**Spelling rule.** A node matcher is the AST class name with a lower-case first letter and the `CXX` prefix folded to `cxx`: `FunctionDecl` → `functionDecl`, `CXXRecordDecl` → `cxxRecordDecl`, `IntegerLiteral` → `integerLiteral`. Get the case wrong and clang-query says `Matcher not found`.

**Typing rule.** Every matcher has a type, written `Matcher<NodeKind>` in the reference's first column. A node matcher such as `functionDecl()` yields a `Matcher<FunctionDecl>`, and it only accepts arguments whose type is `Matcher<FunctionDecl>` or a base of it (`Matcher<NamedDecl>`, `Matcher<Decl>`) — a matcher of the *exact* same type also qualifies, so a node matcher may even nest inside itself (e.g. `functionDecl(functionDecl())`, redundant but legal). `hasName` is a `Matcher<NamedDecl>`, and `FunctionDecl` derives from `NamedDecl`, so `functionDecl(hasName("x"))` type-checks. `hasOperatorName` is a `Matcher<BinaryOperator|…>` — nothing in that list is a base of `FunctionDecl`, so `functionDecl(hasOperatorName("+"))` is a **type error**, not merely "0 matches".

**Arity rule.** A node matcher's parameter *list* is variadic, not fixed: `functionDecl(a, b, c)` takes any number of arguments (0 or more), each checked independently against the typing rule above, and the whole list is combined with an implicit `allOf` (AND). There is no implicit OR — to match if *any* one filter holds, wrap them explicitly in `anyOf(...)`.

Three deliberately broken commands. Throughout this lab, a block inside a `[!warning]` callout is one that fails on purpose — it is shown with its real error text and is not part of the validated examples:

> [!warning]- Wrong spelling
> ```text
> match FunctionDecl()
> 1:1: Matcher not found: FunctionDecl
> ```

> [!warning]- Narrowing matcher outermost
> ```text
> match hasName("add")
> Not a valid top-level matcher.
> ```

> [!warning]- Type mismatch
> ```text
> match functionDecl(hasOperatorName("+"))
> 1:1: Error building matcher functionDecl.
> 1:14: Incorrect type for arg 1. (Expected = Matcher<FunctionDecl>) != (Actual = Matcher<BinaryOperator|CXXOperatorCallExpr|CXXRewrittenBinaryOperator|CXXFoldExpr|UnaryOperator>)
> ```

The fix for the last one is to put `hasOperatorName` inside a frame of the right kind. `binaryOperator()` yields `Matcher<BinaryOperator>`, which is in the accepted list:

```clang-query
match binaryOperator(hasOperatorName("+"))
```

**Expected:** 4 matches — the `+` in `add` (`intro.cpp:3`), the two `+` in `total` (`intro.cpp:5`, one nested inside the other), and the `+` in `Point::sum` (`intro.cpp:10`).

To ask the original question ("functions that contain a `+`") you *traverse* from the function frame to a `BinaryOperator` frame with `hasDescendant`, whose argument may be any matcher type:

```clang-query
match functionDecl(hasName("total"),
  hasDescendant(binaryOperator(hasOperatorName("+"))))
```

**Expected:** 1 match — `total` at `intro.cpp:5`.

Notice that the outermost node matcher decides **what is reported**: the match above is the function, not the `+`. Section 1.4 shows how to also see the inner node.

## 1.4 — Match output

By default clang-query prints, for every match, a diagnostic-style location for each **bound node**, then a final `N match(es).` line. Two things to know about bindings:

- The outermost matcher is bound to the name **`root`** automatically. That is why the plain matches above print `"root" binds here`.
- `.bind("name")` may be appended to *any node matcher* (never to a narrowing or traversal matcher) to record that node under a name as well.

```clang-query
match functionDecl(hasName("twice"), hasDescendant(callExpr().bind("call")))
```

**Expected:** 1 match — `"call"` binds at `intro.cpp:4:27` (the `add(x, x)` call) and `"root"` binds at `intro.cpp:4:1` (the function).

`set bind-root false` turns the implicit root binding off, so only your own `.bind` names are reported (with no bindings at all, a match prints `No bindings.`):

```clang-query
set bind-root false
match functionDecl(hasName("twice"), hasDescendant(callExpr().bind("call")))
```

**Expected:** 1 match — only `"call"` at `intro.cpp:4:27` is printed.

**Output features.** `set output <feature>` chooses *exclusively* what is printed per bound node; `enable output` / `disable output` add or remove a feature without touching the others.

| Feature | Prints per bound node |
|---------|-----------------------|
| `diag` | `file:line:col: note: "name" binds here` plus the source line (the default) |
| `print` | The node pretty-printed back as C++ source |
| `detailed-ast` | The AST subtree, exactly as `clang -Xclang -ast-dump` would show it |
| `dump` | Alias of `detailed-ast` |

```clang-query
set output print
match functionDecl(hasName("add"))
```

**Expected:** 1 match — printed as source: `int add(int a, int b) { return a + b; }`.

```clang-query
set output dump
match functionDecl(hasName("twice"))
```

**Expected:** 1 match — an AST dump: `FunctionDecl … twice 'int (int)'` with a `ParmVarDecl`, a `CompoundStmt`, a `ReturnStmt`, a `CallExpr`, and the `ImplicitCastExpr` / `DeclRefExpr` nodes under it.

That dump is the single most useful thing in this lab. When a matcher returns 0 matches and you do not know why, dump the node you *expected* to match and compare its real children with what your matcher assumed. Keep `diag` for locations and add `print` on top:

```clang-query
enable output print
match functionDecl(hasName("add"))
```

**Expected:** 1 match — both the `binds here` location and the pretty-printed source.

`set print-matcher true` echoes the matcher above its results, which is handy in scripts:

```clang-query
set print-matcher true
match functionDecl(hasName("add"))
```

**Expected:** 1 match — preceded by a `Matcher: functionDecl(hasName("add"))` banner.

## 1.5 — `let` and query files

`let NAME MATCHER` gives a matcher expression a name for the rest of the session. The name may then be used anywhere a matcher is expected, including as the outermost matcher and with `.bind` appended:

```clang-query
let plusOp binaryOperator(hasOperatorName("+"))
let addsSomething functionDecl(hasDescendant(plusOp))
match addsSomething
```

**Expected:** 3 matches — `add` (`intro.cpp:3`), `total` (`intro.cpp:5`) and `Point::sum` (`intro.cpp:10`).

```clang-query
let plusOp binaryOperator(hasOperatorName("+"))
match plusOp.bind("op")
```

**Expected:** 4 matches — the same four `+` operators as in section 1.3, each now also bound as `"op"`.

Once a matcher has more than two levels, keep it in a file. `manifests/intro.query` is that session as a script:

```text
# intro.query — a clang-query script. Run with:
#   $LLVM/bin/clang-query -f manifests/intro.query manifests/intro.cpp -- -std=c++23

set output diag
set print-matcher true

# name the pieces once ...
let plusOp binaryOperator(hasOperatorName("+"))
let addsSomething functionDecl(hasDescendant(plusOp))

# ... then use them
match addsSomething
match plusOp.bind("op")
```

```bash
$LLVM/bin/clang-query -f manifests/intro.query manifests/intro.cpp -- -std=c++23
```

You should see the `Matcher: addsSomething` banner followed by `3 matches.`, then `Matcher: plusOp.bind("op")` followed by `4 matches.`. Two details about script files: `#` comments are allowed anywhere, and a `quit` line inside a `-f` file is ignored — the tool exits when the file ends, so there is no need for one.

## 1.6 — Traversal modes

Clang's AST contains far more than you typed. Implicit casts, elided constructor calls, compiler-generated special members, template instantiations and the hidden `begin()`/`end()` calls of a range-`for` are all real nodes. By default matchers see all of them: this is **`AsIs`** mode. **`IgnoreUnlessSpelledInSource`** mode hides every node that has no spelling in the source, so a matcher can be written against the code as the programmer sees it.

In the C++ API the switch is the `traverse(TK_…, matcher)` wrapper; that name is **not** registered in clang-query. The clang-query equivalent is a session setting:

```text
set traversal AsIs                          # default
set traversal IgnoreUnlessSpelledInSource
```

The reference introduces the modes with this example, reproduced at `intro.cpp:15-18`:

```cpp
struct B {
  B(int);
};
B func1() { return 42; }
```

Look at what `return 42;` really is in AsIs mode:

```clang-query
set output dump
match returnStmt(hasDescendant(integerLiteral(equals(42))))
```

**Expected:** 1 match — `ReturnStmt` → `ImplicitCastExpr <ConstructorConversion>` → `CXXConstructExpr 'void (int)'` → `IntegerLiteral 42`.

So `hasReturnValue(integerLiteral())` cannot match: the return value is the cast, not the literal. The reference's AsIs matcher for this case peels every wrapper the compiler can insert, then names the conversion constructor explicitly and looks at *its* argument:

```clang-query
match functionDecl(hasName("func1"),
  hasDescendant(returnStmt(hasReturnValue(
    ignoringImplicit(ignoringElidableConstructorCall(
      ignoringImplicit(cxxConstructExpr(hasArgument(0,
        ignoringImplicit(integerLiteral()))))))))))
```

**Expected:** 1 match — `func1` at `intro.cpp:18:1`.

The reference labels this matcher "All dialects" because the number of wrappers changes with the language standard but the innermost node does not. Under `-std=c++14` the return value is `ExprWithCleanups` → *elidable* `CXXConstructExpr 'B(B&&)'` → `MaterializeTemporaryExpr` → `ImplicitCastExpr` → `CXXConstructExpr 'B(int)'` → `IntegerLiteral`: the first `ignoringImplicit` strips `ExprWithCleanups`, `ignoringElidableConstructorCall` strips the elidable move and its `MaterializeTemporaryExpr`, the second `ignoringImplicit` strips the cast. Under `-std=c++23` guaranteed copy elision removes the first three nodes, so the two outer wrappers are no-ops and the tree is the one you just dumped. Either way the matcher lands on the `B(int)` call — a real user-written conversion, neither implicit nor elidable, so no `ignoring*` wrapper skips it. The only route to the `42` is `hasArgument(0, …)`; drop that `cxxConstructExpr(hasArgument(0, …))` layer and write `ignoringImplicit(integerLiteral())` directly, and the matcher matches in **no** dialect.

Because the two outer wrappers only matter for pre-C++17 trees, on this lab's `-std=c++23` you can shorten it — at the cost of dialect-independence (under `-std=c++14` this version is 0 matches: `cxxConstructExpr` then matches the elidable move constructor, whose argument is the `B(int)` call, not the literal):

```clang-query
match returnStmt(hasReturnValue(ignoringImplicit(
  cxxConstructExpr(hasArgument(0, ignoringImplicit(integerLiteral()))))))
```

**Expected:** 1 match — the `return 42;` at `intro.cpp:18:13`.

Both versions encode knowledge about implicit nodes that also changes between language standards. In `IgnoreUnlessSpelledInSource` mode the implicit cast and the conversion constructor vanish from the tree and the matcher is what you would have written first:

```clang-query
set traversal IgnoreUnlessSpelledInSource
match returnStmt(hasReturnValue(integerLiteral()))
```

**Expected:** 1 match — `return 42;` at `intro.cpp:18:13`.

The same short matcher in the default mode, for contrast:

```clang-query
match returnStmt(hasReturnValue(integerLiteral()))
```

**Expected:** 0 matches — in AsIs mode the return value is the `ImplicitCastExpr`.

The reference lists three more situations where AsIs produces matches a refactoring tool would *not* want. All three are in `intro.cpp`.

**Case 1 — compiler-generated copy constructors** (`intro.cpp:20-25`, `struct Foo {}` and `Foo g = f;`). A tool that rewrites copy constructors must not touch ones the compiler declared:

```clang-query
match cxxConstructorDecl(isCopyConstructor())
```

**Expected:** 5 matches — none of them spelled in the source: the implicit copy constructors of `B` (`intro.cpp:15`), `Foo` (`intro.cpp:20`), `Cont` (`intro.cpp:27`), and of the two instantiations `TemplStruct<int>` and `TemplStruct<double>` (both reported at `intro.cpp:40`).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match cxxConstructorDecl(isCopyConstructor())
```

**Expected:** 0 matches — the sample declares no copy constructor.

**Case 2 — range-`for` calls `begin()` for you** (`intro.cpp:31-36`). A tool renaming `begin()` calls to `cbegin()` must not rewrite the hidden call generated by `for (auto i : c)`:

```clang-query
match callExpr(callee(functionDecl(hasName("begin"))))
```

**Expected:** 1 match — the implicit `begin()` call of the range-`for` at `intro.cpp:34`; nothing in the source spells `begin(`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match callExpr(callee(functionDecl(hasName("begin"))))
```

**Expected:** 0 matches.

**Case 3 — template instantiations** (`intro.cpp:39-49`). `TemplStruct` has one field `T m_t`; `instantiate()` creates `TemplStruct<int>` and `TemplStruct<double>`. A tool that renames every `int` field to `safe_int` would "find" `m_t` in the `int` instantiation and rewrite the template, breaking the `double` one:

```clang-query
match fieldDecl(hasName("m_t"))
```

**Expected:** 3 matches — the template's field and one per instantiation, all reported at `intro.cpp:44`.

```clang-query
match fieldDecl(hasName("m_t"), hasType(asString("int")))
```

**Expected:** 1 match — `m_t` inside `TemplStruct<int>`, reported at `intro.cpp:44` although no `int m_t` exists in the source.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match fieldDecl(hasName("m_t"))
```

**Expected:** 1 match — only the template's own `T m_t` at `intro.cpp:44`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match fieldDecl(hasName("m_t"), hasType(asString("int")))
```

**Expected:** 0 matches — the only spelled field has type `T`.

One more AsIs artefact worth knowing early, because it inflates counts in Part 2: every class contains an implicit *injected class name* declaration with the same name as the class.

```clang-query
match namedDecl(hasName("Point"))
```

**Expected:** 2 matches — both reported at `intro.cpp:7`: the `struct Point` itself and its injected class name.

```clang-query
match cxxRecordDecl(hasName("Point"), unless(isImplicit()))
```

**Expected:** 1 match — `Point` at `intro.cpp:7`. (`set traversal IgnoreUnlessSpelledInSource` gives the same count without the `unless`.)

**Which mode should you use?** `IgnoreUnlessSpelledInSource` whenever a matcher describes *source code* (linting, refactoring); `AsIs` when the implicit nodes are the point (finding implicit conversions, checking what a template instantiates to). Parts 2–11 run in `AsIs` unless an entry says otherwise, because the reference's own counts are AsIs counts.

## 1.7 — Children, descendants, and the logical matchers

Three traversal matchers look alike and behave differently. On `total` (`intro.cpp:5`, `return 1 + 2 + 3;`):

```clang-query
match functionDecl(hasName("total"), has(integerLiteral()))
```

**Expected:** 0 matches — `has` looks only at *direct children*, and the function's child is its `CompoundStmt`.

```clang-query
match functionDecl(hasName("total"), has(compoundStmt()))
```

**Expected:** 1 match — `total` at `intro.cpp:5`.

```clang-query
match functionDecl(hasName("total"), hasDescendant(integerLiteral()))
```

**Expected:** 1 match — `hasDescendant` searches the whole subtree and succeeds on the *first* literal it finds.

```clang-query
match functionDecl(hasName("total"), forEachDescendant(integerLiteral()))
```

**Expected:** 1 match — surprising until you know the rule: clang-query counts **distinct sets of bound nodes**. `forEachDescendant` did fire three times, but each time the only bound node was `root` (= `total`), so the three results collapse into one.

```clang-query
match functionDecl(hasName("total"), forEachDescendant(integerLiteral().bind("lit")))
```

**Expected:** 3 matches — one per literal (`intro.cpp:5:22`, `5:26`, `5:30`), because `"lit"` now differs between results. Remember this: **bind what you iterate**.

Four logical matchers combine anything of any type; they appear in nearly every real query and get their full entries in Part 10:

```clang-query
match functionDecl(anyOf(hasName("add"), hasName("twice")))
```

**Expected:** 2 matches — `add` (`intro.cpp:3`) and `twice` (`intro.cpp:4`).

```clang-query
match functionDecl(allOf(hasName("add"), parameterCountIs(2)))
```

**Expected:** 1 match — `add`. Listing several arguments in a node matcher is an implicit `allOf`, so `functionDecl(hasName("add"), parameterCountIs(2))` is the same query.

```clang-query
match functionDecl(hasName("add"), unless(parameterCountIs(3)))
```

**Expected:** 1 match — `unless` negates its argument.

```clang-query
match functionDecl(hasName("add"), hasParameter(0, anything()))
```

**Expected:** 1 match — `anything()` matches every node; use it when a traversal matcher demands an argument but you do not care what it finds ("has a first parameter").

## 1.8 — How to read a reference entry

Every row of https://clang.llvm.org/docs/LibASTMatchersReference.html has the same three parts. Take the `hasName` row of the *Narrowing Matchers* table:

| Column | Value | What it tells you |
|--------|-------|-------------------|
| Return type | `Matcher<NamedDecl>` | Which frame it plugs into: any node matcher whose kind is `NamedDecl` or derives from it (`functionDecl`, `varDecl`, `cxxRecordDecl`, …). |
| Name + parameters | `hasName(StringRef Name)` | How to spell the call; `StringRef` means a quoted string, `unsigned N` a number, `Matcher<X>` another matcher. |
| Description | "Matches NamedDecl nodes that have the specified name … Given `namespace a { namespace b { class C; } }` … `recordDecl(hasName("C"))` matches `C`." | The plain-English rule, then a "Given … matches …" example. |

The **Node Matchers** table is organised by return type too: `Matcher<Decl>` rows are the node matchers that stand on a declaration frame, `Matcher<Stmt>` rows on a statement frame, and so on. Polymorphic matchers (`has`, `hasDescendant`, `anyOf`, …) are listed as `Matcher<*>`.

Parts 2–11 mirror this exactly. Each reference row becomes one entry whose heading repeats the row (shown here as a template, not a runnable example — `Circle` lives in Part 2's sample):

> [!example]- Entry template
> ```text
> ### `hasName(StringRef Name)` — Matcher<NamedDecl>
>
> <one to three sentences: what it matches, in plain English>
>
> match namedDecl(hasName("Circle"))
>
> **Expected:** 1 match — `Circle` at `decls.cpp:12`.
> ```

The heading gives you the return type (where it plugs in) and the parameters (how to call it); the block is the reference's "Given … matches …" example turned into something you can run; the **Expected** line is the count and location you should see. Overloads of one name share an entry and list every return type after the dash. Fourteen reference names are not registered in this clang-query build (among them `traverse`, `findAll`, `equalsNode`, `cxxNamedCastExpr`, `functionTypeLoc`, `requiresExpr`, and several `omp…` matchers); their entries keep the heading, say **Not in clang-query 22**, and show the nearest working alternative.

## 1.9 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Tool invocation | `clang-query file -- flags` works; `-c` and `-f` run the same commands non-interactively. |
| Node / narrowing / traversal | Only node matchers may be outermost; narrowing filters a frame; traversal opens a new frame. |
| Typing | `functionDecl(hasOperatorName("+"))` is a type error; `binaryOperator(hasOperatorName("+"))` matches 4 operators. |
| Bindings and output | `root` is implicit; `.bind` names inner nodes; `set output dump` shows the real tree. |
| `let` and scripts | Named sub-matchers compose; `intro.query` runs with `-f`. |
| Traversal modes | The copy-constructor, `begin()` and `m_t` counts drop from 5/1/3 to 0/0/1 under `IgnoreUnlessSpelledInSource`. |
| `has` / `hasDescendant` / `forEachDescendant` | 0 / 1 / 1 on `total`, and 3 once the descendant is bound. |
| Reading the reference | Return type = where it plugs in; parameters = how to call it. |

**Quiz.** In `IgnoreUnlessSpelledInSource` mode, find every function whose body contains a call to a function named `add`. You need a node matcher, a traversal into the body, a `callExpr`, a traversal to its callee, and a narrowing matcher on the name.

> [!hint]- Hint
> `callee(...)` is a traversal matcher that moves from a `CallExpr` to the declaration being called; put `functionDecl(hasName("add"))` inside it. Wrap the whole thing in `hasDescendant` from a `functionDecl` frame.

> [!success]- Answer
> ```text
> set traversal IgnoreUnlessSpelledInSource
> match functionDecl(hasDescendant(callExpr(callee(functionDecl(hasName("add"))))))
> ```
> 1 match — `twice` at `intro.cpp:4`. The same query in `AsIs` mode also gives 1, because a plain call has no implicit nodes to hide.

---

[← README](README.md) | [Part 2 — Node Matchers I — Declarations →](part_2_node_matchers_decls.md)
