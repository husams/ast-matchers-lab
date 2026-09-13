# Part 3 — Node Matchers II — Statements & Expressions

[← Part 2 — Node Matchers I — Declarations](part_2_node_matchers_decls.md) | [Part 4 — Node Matchers III — Types & TypeLocs →](part_4_node_matchers_types.md)

**Sample:** `manifests/stmts.cpp` · flags: `-std=c++23`

## What You'll Learn

- How every statement and expression in Clang lives in **one** hierarchy rooted at `Stmt`, and why `expr()` is just a narrower `stmt()`.
- The node matcher for every kind of statement (control flow, jumps, labels, blocks, exceptions) and expression (literals, names, operators, calls, casts, construction).
- That the AST contains **invisible nodes** you never typed — implicit casts, temporaries, cleanups, array-copy loops, default arguments — and how to see them.
- How templates leave **dependent** nodes behind (`t.g()`, `T::v`, `T(t)`) that only resolve at instantiation.
- Where coroutines and the C / GNU extensions (`_Generic`, `({ … })`, `&&label`, `__atomic_*`, fixed-point) show up in the tree.
- How to narrow a "match everything" node matcher so its count is meaningful.

## The Big Picture

Part 2 dealt with **declarations** — things that introduce a name. This part is about the **code inside function bodies**: statements that do something and expressions that produce a value. In Clang they are one family. `Stmt` is the root; `Expr` is a subclass of `Stmt` that adds a type and a value category. So every expression is also a statement, and `stmt()` matches every node this part covers, while `expr()` matches only the value-producing subset.

```
Stmt
├── CompoundStmt  IfStmt  ForStmt  WhileStmt  SwitchStmt  ReturnStmt  DeclStmt  …   (no value)
└── Expr                                                                          (type + value)
    ├── literals        IntegerLiteral  FloatingLiteral  StringLiteral  CXXBoolLiteralExpr …
    ├── names           DeclRefExpr  MemberExpr  CXXThisExpr
    ├── operators       UnaryOperator  BinaryOperator  ConditionalOperator  CXXOperatorCallExpr
    ├── calls           CallExpr ── CXXMemberCallExpr    CXXConstructExpr ── CXXTemporaryObjectExpr
    ├── casts           CastExpr ── ImplicitCastExpr | ExplicitCastExpr ── CStyleCastExpr, CXXStaticCastExpr …
    ├── invisible       ExprWithCleanups  MaterializeTemporaryExpr  CXXBindTemporaryExpr  ImplicitValueInitExpr
    └── dependent       CXXDependentScopeMemberExpr  UnresolvedLookupExpr  CXXUnresolvedConstructExpr …
```

Two facts make this part different from Part 2:

1. **The tree is bigger than the source.** Clang inserts nodes you never wrote: an `ImplicitCastExpr` for every lvalue-to-rvalue read, a `MaterializeTemporaryExpr` when a prvalue needs an address, a `CXXDefaultArgExpr` where a default argument is filled in, an `ArrayInitLoopExpr` inside an implicit copy constructor. `stmt()` on our 247-line sample matches 985 nodes; `expr()` matches 787. Most of them are invisible.
2. **Bare node matchers are rarely useful alone.** `integerLiteral()` matches 100 nodes in the sample. Every example below narrows with a second matcher — `equals(7)`, `hasAncestor(functionDecl(hasName("f")))`, `has(varDecl(hasName("i")))` — so the count you see is one you can check by eye. The prose tells you what the unnarrowed matcher would cover. Those narrowing matchers come from later parts; for now read them as English.

The sample `manifests/stmts.cpp` is one file with ten sections that mirror the sections below, plus a short block of hand-written `std::` stubs at the top (`initializer_list`, `strong_ordering`, `coroutine_traits`, `coroutine_handle`, `suspend_never`) so it needs no `#include`. Keep it open beside the session: every **Expected** line cites its line numbers.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/stmts.cpp -- -std=c++23
```

---

## 3.1 — Statements: blocks, control flow, jumps, exceptions

A statement is a unit of execution. The matchers here are one per keyword: `if`, `for`, `while`, `do`, `switch`, `case`, `default`, `break`, `continue`, `return`, `goto`, a label, `try`, `catch`, `throw`, plus the three structural ones — the compound block `{ … }`, the empty statement `;`, and the declaration statement `int i = 0;`. The sample's `statements` function (lines 56–73) uses each of them once.

### `stmt(Matcher<Stmt>...)` — Matcher<Stmt>

Matches every statement and expression node — the root of this whole part. On its own it matches 985 nodes in the sample, so we narrow to the one-line function `returns` at line 75. Its body `{ return x + 1; }` is six nodes: the compound block, the `return`, the `+`, an implicit lvalue-to-rvalue cast of `x`, the reference to `x`, and the literal `1`.

```text
clang-query> match stmt(hasAncestor(functionDecl(hasName("returns"))))
```

**Expected:** 6 matches — `{ … }` at `stmts.cpp:75:20`, `return` at `75:22`, `x + 1`, the implicit cast, `x` (all `75:29`) and `1` at `75:33`.

### `expr(Matcher<Expr>...)` — Matcher<Stmt>

Matches expressions only — the value-producing subset of `stmt()`. Same function, same tree: drop the two nodes that have no value (the block and the `return`) and four remain. Bare `expr()` matches 787 nodes in the sample.

```text
clang-query> match expr(hasAncestor(functionDecl(hasName("returns"))))
```

**Expected:** 4 matches — `x + 1`, the implicit cast of `x`, `x` (all at `stmts.cpp:75:29`) and `1` at `75:33`.

### `compoundStmt(Matcher<CompoundStmt>...)` — Matcher<Stmt>

Matches a brace block `{ … }`, including empty ones. Blocks nest — a function body, a `try` block and a `catch` block are three separate compound statements. Bare `compoundStmt()` matches 66 blocks in the sample (the stubs have many one-line bodies).

```text
clang-query> match compoundStmt(hasAncestor(functionDecl(hasName("exceptions"))))
```

**Expected:** 3 matches — the body of `exceptions` at `stmts.cpp:77:19`, the `try {}` block at `78:7`, the `catch` block at `78:32`.

### `nullStmt(Matcher<NullStmt>...)` — Matcher<Stmt>

Matches the empty statement — a lone `;`. Common as the body of a busy-wait loop or as a stray double semicolon.

```text
clang-query> match nullStmt()
```

**Expected:** 1 match — the bare `;` at `stmts.cpp:58:3`.

### `declStmt(Matcher<DeclStmt>...)` — Matcher<Stmt>

Matches a statement that declares something inside a body, such as `int i = 0;`. The `DeclStmt` node wraps the `VarDecl` (Part 2); `has(varDecl(…))` reaches through it. Bare `declStmt()` matches 70 in the sample.

```text
clang-query> match declStmt(has(varDecl(hasName("i"))))
```

**Expected:** 1 match — `int i = 0;` at `stmts.cpp:57:3`.

Range-based `for` shows how many declarations Clang desugars into. Restrict to the `statements` function and you get the two you wrote (`i` and `arr`), the loop variable `k` of the classic `for`, and four hidden ones from `for (int e : arr)` — `__range1`, `__begin1`, `__end1` and `e`.

```text
clang-query> match declStmt(hasAncestor(functionDecl(hasName("statements"))))
```

**Expected:** 7 matches — `stmts.cpp:57:3`, `63:3`, `60:8` and four at `64:8`–`64:16` for the range-for.

### `ifStmt(Matcher<IfStmt>...)` — Matcher<Stmt>

Matches an `if` statement, with or without `else`, including `if constexpr` and `if` with an initializer. Bare `ifStmt()` gives 5 here: the three you wrote plus two Clang synthesizes inside the defaulted `operator<=>` at line 121 (which compares members one by one).

```text
clang-query> match ifStmt(hasAncestor(functionDecl(hasName("statements"))))
```

**Expected:** 3 matches — `if (a > 0) … else …` at `stmts.cpp:59:3`, `if (k == 3)` at `60:33`, `if (k == 1)` at `60:52`.

### `forStmt(Matcher<ForStmt>...)` — Matcher<Stmt>

Matches a classic three-clause `for` loop. Range-based `for` is a different node (`cxxForRangeStmt`), so this does not match line 64.

```text
clang-query> match forStmt()
```

**Expected:** 1 match — `for (int k = 0; k < n; ++k)` at `stmts.cpp:60:3`.

### `whileStmt(Matcher<WhileStmt>...)` — Matcher<Stmt>

Matches a `while` loop.

```text
clang-query> match whileStmt()
```

**Expected:** 1 match — `while (i < 10)` at `stmts.cpp:61:3`.

### `doStmt(Matcher<DoStmt>...)` — Matcher<Stmt>

Matches a `do … while` loop.

```text
clang-query> match doStmt()
```

**Expected:** 1 match — `do { --i; } while (i > 0);` at `stmts.cpp:62:3`.

### `cxxForRangeStmt(Matcher<CXXForRangeStmt>...)` — Matcher<Stmt>

Matches a range-based `for`. Clang keeps the sugared form as one node and hangs the desugared `__begin`/`__end` machinery underneath it, which is why the `declStmt` example above found four hidden declarations.

```text
clang-query> match cxxForRangeStmt()
```

**Expected:** 1 match — `for (int e : arr)` at `stmts.cpp:64:3`.

### `switchStmt(Matcher<SwitchStmt>...)` — Matcher<Stmt>

Matches a `switch` statement. Its `case` and `default` labels are separate child nodes (next three entries).

```text
clang-query> match switchStmt()
```

**Expected:** 1 match — `switch (a)` at `stmts.cpp:65:3`.

### `caseStmt(Matcher<CaseStmt>...)` — Matcher<Stmt>

Matches a `case` label inside a `switch`. The label owns the statement that follows it, so `case 37: i = 37;` is one `CaseStmt` containing an assignment.

```text
clang-query> match caseStmt()
```

**Expected:** 1 match — `case 37:` at `stmts.cpp:66:3`.

### `defaultStmt(Matcher<DefaultStmt>...)` — Matcher<Stmt>

Matches the `default:` label of a `switch`.

```text
clang-query> match defaultStmt()
```

**Expected:** 1 match — `default:` at `stmts.cpp:67:3`.

### `switchCase(Matcher<SwitchCase>...)` — Matcher<Stmt>

Matches both `case` and `default` labels — `SwitchCase` is their common base class. Use it when you want "every label in this switch" without caring which kind.

```text
clang-query> match switchCase()
```

**Expected:** 2 matches — `case 37:` at `stmts.cpp:66:3` and `default:` at `67:3`.

### `breakStmt(Matcher<BreakStmt>...)` — Matcher<Stmt>

Matches `break`, whether it leaves a loop or a `switch`. The sample has one of each kind.

```text
clang-query> match breakStmt()
```

**Expected:** 3 matches — inside the `for` at `stmts.cpp:60:45`, in `case 37:` at `66:20`, in `default:` at `67:19`.

### `continueStmt(Matcher<ContinueStmt>...)` — Matcher<Stmt>

Matches `continue`.

```text
clang-query> match continueStmt()
```

**Expected:** 1 match — `continue` at `stmts.cpp:60:64`.

### `returnStmt(Matcher<ReturnStmt>...)` — Matcher<Stmt>

Matches a `return`, with or without a value. Bare `returnStmt()` matches 35 in the sample because every stub method and lambda returns something, so narrow by function.

```text
clang-query> match returnStmt(hasAncestor(functionDecl(hasName("returns"))))
```

**Expected:** 1 match — `return x + 1;` at `stmts.cpp:75:22`.

### `gotoStmt(Matcher<GotoStmt>...)` — Matcher<Stmt>

Matches a `goto label;`. (Computed `goto *ptr` is a different node, `IndirectGotoStmt`, which has no matcher.)

```text
clang-query> match gotoStmt()
```

**Expected:** 1 match — `goto done;` at `stmts.cpp:69:3`.

### `labelStmt(Matcher<LabelStmt>...)` — Matcher<Stmt>

Matches a label definition `name:` together with the statement it labels. The sample has one in `statements` and one in `exotic` (the target of the `&&exit_label` address-of-label).

```text
clang-query> match labelStmt()
```

**Expected:** 2 matches — `done:` at `stmts.cpp:70:1` and `exit_label:` at `245:1`.

### `cxxTryStmt(Matcher<CXXTryStmt>...)` — Matcher<Stmt>

Matches a `try` block together with its handlers.

```text
clang-query> match cxxTryStmt()
```

**Expected:** 1 match — `try { throw 5; } catch (int) { }` at `stmts.cpp:78:3`.

### `cxxCatchStmt(Matcher<CXXCatchStmt>...)` — Matcher<Stmt>

Matches one `catch (…) { … }` handler. A `try` with three handlers yields three `CXXCatchStmt` nodes.

```text
clang-query> match cxxCatchStmt()
```

**Expected:** 1 match — `catch (int) { }` at `stmts.cpp:78:20`.

### `cxxThrowExpr(Matcher<CXXThrowExpr>...)` — Matcher<Stmt>

Matches a `throw` expression — `throw 5` and the bare rethrow `throw;` alike. Note it is an *expression* (it has type `void`), so it also answers to `expr()`.

```text
clang-query> match cxxThrowExpr()
```

**Expected:** 1 match — `throw 5` at `stmts.cpp:78:9`.

---

## 3.2 — Literals and initializers

A literal is a value spelled directly in source. Clang has one node per lexical kind — integer, floating, imaginary, fixed-point, character, string, `true`/`false`, `nullptr`, user-defined `_suffix` — plus the brace-initializer family (`{1, 2}`, `{.x = 1}`, `std::initializer_list` backing, C99 compound literals). The `literals` function at lines 85–105 has one of each.

### `integerLiteral(Matcher<IntegerLiteral>...)` — Matcher<Stmt>

Matches an integer literal of any size or base: `7`, `7L`, `0x1`, `1U`. A character like `'a'` is *not* an integer literal (see `characterLiteral`), and neither is an enumerator or a `constexpr` variable. Bare `integerLiteral()` matches 100 nodes in the sample — every `0`, `1`, `2` in loops, initializers and stubs — so narrow with a value.

```text
clang-query> match integerLiteral(equals(7))
```

**Expected:** 2 matches — `7` at `stmts.cpp:86:13` and `7L` at `87:14`.

### `floatLiteral(Matcher<FloatingLiteral>...)` — Matcher<Stmt>

Matches a floating-point literal of any width or suffix: `2.5`, `1.0f`, `1e10`, `1.0L`. It does not match an implicit conversion such as `float a = 10;`. Note the fourth hit: the `1.0` inside the imaginary literal `1.0i` is a `FloatingLiteral` wrapped by an `ImaginaryLiteral`.

```text
clang-query> match floatLiteral()
```

**Expected:** 4 matches — `2.5` at `stmts.cpp:88:14`, `1.0f` at `89:13`, the `1.0` inside `1.0i` at `96:23`, `2.2f` at `162:24`.

### `imaginaryLiteral(Matcher<ImaginaryLiteral>...)` — Matcher<Stmt>

Matches a GNU imaginary constant such as `1i` or `1.0i`, used with `_Complex` types. The node wraps an integer or floating literal.

```text
clang-query> match imaginaryLiteral()
```

**Expected:** 1 match — `1.0i` at `stmts.cpp:96:23`.

### `fixedPointLiteral(Matcher<FixedPointLiteral>...)` — Matcher<Stmt>

Matches a fixed-point literal from the Embedded C extension — `0.5r`, `1.0k`, `1.25hk`, `1.575e1k`, `0x0.2p2r` and so on. These need the `_Accum`/`_Fract` types and the `-ffixed-point` flag, and they are a C feature, so this entry uses a separate C sample. An implicit conversion such as `_Accum a = 12.5;` is a floating literal, not a fixed-point one.

```text
# sample: manifests/stmts_fixedpoint.c -ffixed-point
clang-query> match fixedPointLiteral()
```

**Expected:** 4 matches — `1.25hk`, `0.25hr`, `1.45uhk`, `1.575e1k` at `stmts_fixedpoint.c:5:12`, `6:12`, `7:12`, `8:12`.

### `characterLiteral(Matcher<CharacterLiteral>...)` — Matcher<Stmt>

Matches a character literal of any encoding: `'a'`, `L'a'`, `u8'a'`, `U'a'`. A hex number like `0x61` is an `IntegerLiteral` even though it fits in a `char`.

```text
clang-query> match characterLiteral()
```

**Expected:** 2 matches — `'a'` at `stmts.cpp:90:12` and `L'a'` at `91:16`.

### `stringLiteral(Matcher<StringLiteral>...)` — Matcher<Stmt>

Matches a string literal of any encoding, including wide and raw strings. Strings hide in places you may not expect: the template of an `asm` statement, the association results of `_Generic`, and the string that backs `__func__` are all `StringLiteral` nodes.

```text
clang-query> match stringLiteral()
```

**Expected:** 6 matches — `"nop"` in the `asm` at `stmts.cpp:72:16`, `"abcd"` at `92:19`, `L"abcd"` at `93:23`, the string behind `__func__` at `103:20`, `"int"` and `"float"` at `242:41` and `242:56`.

### `cxxBoolLiteral(Matcher<CXXBoolLiteralExpr>...)` — Matcher<Stmt>

Matches `true` or `false`. Bare `cxxBoolLiteral()` also finds the two `return true;` lines in the coroutine stubs, so narrow by function.

```text
clang-query> match cxxBoolLiteral(hasAncestor(functionDecl(hasName("literals"))))
```

**Expected:** 1 match — `true` at `stmts.cpp:94:12`.

### `cxxNullPtrLiteralExpr(Matcher<CXXNullPtrLiteralExpr>...)` — Matcher<Stmt>

Matches the `nullptr` keyword. Plain `0` or `NULL` used as a pointer is an integer literal with an implicit null-pointer cast, not this node; GNU `__null` is `gnuNullExpr` (section 3.10).

```text
clang-query> match cxxNullPtrLiteralExpr(hasAncestor(functionDecl(hasName("literals"))))
```

**Expected:** 1 match — `nullptr` at `stmts.cpp:95:13`.

### `userDefinedLiteral(Matcher<UserDefinedLiteral>...)` — Matcher<Stmt>

Matches a call to a user-defined literal operator: `4_kb` is really `operator""_kb(4ULL)`. `UserDefinedLiteral` is a subclass of `CallExpr`, so `callExpr()` matches it too.

```text
clang-query> match userDefinedLiteral()
```

**Expected:** 1 match — `4_kb` at `stmts.cpp:97:13`.

### `initListExpr(Matcher<InitListExpr>...)` — Matcher<Stmt>

Matches a braced initializer list `{1, 2}`. Clang stores each list twice — a *syntactic* form as written and a *semantic* form with conversions and fill-ins — but `initListExpr()` reports the node once. Bare `initListExpr()` matches 22 in the sample; the `literals` function holds five, including the designated, the partial, the `std::initializer_list` and the compound-literal ones.

```text
clang-query> match initListExpr(hasAncestor(functionDecl(hasName("literals"))))
```

**Expected:** 5 matches — `{1, 2}` at `stmts.cpp:98:13`, `{.x = 3, .y = 4}` at `99:13`, `{5}` at `100:16`, `{1, 2, 3}` at `101:16`, `{9, 8}` at `102:21`.

### `designatedInitExpr(Matcher<DesignatedInitExpr>...)` — Matcher<Stmt>

Matches one designated initializer `.field = value` (C99, and C++20 in this sample). A list with two designators yields two nodes, one per designation.

```text
clang-query> match designatedInitExpr()
```

**Expected:** 2 matches — `.x = 3` at `stmts.cpp:99:14` and `.y = 4` at `99:22`.

### `cxxStdInitializerListExpr(Matcher<CXXStdInitializerListExpr>...)` — Matcher<Stmt>

Matches the node Clang builds when a braced list is passed to a `std::initializer_list<T>` parameter: it wraps the `InitListExpr` and materializes the hidden backing array. Aggregate initialization (`Point p = {1, 2}`) never produces it, only constructor calls with an `initializer_list` parameter do.

```text
clang-query> match cxxStdInitializerListExpr()
```

**Expected:** 1 match — `{1, 2, 3}` passed to `IntList` at `stmts.cpp:101:16`.

### `compoundLiteralExpr(Matcher<CompoundLiteralExpr>...)` — Matcher<Stmt>

Matches a C99 compound literal `(Type){ … }` — a cast-like spelling that creates an unnamed object. Clang accepts it in C++ as an extension.

```text
clang-query> match compoundLiteralExpr()
```

**Expected:** 1 match — `(Point){9, 8}` at `stmts.cpp:102:14`.

---

## 3.3 — Names and members

Three nodes cover "use of a name": `DeclRefExpr` (a plain name that refers to a declaration), `MemberExpr` (`obj.field`, `ptr->method`, or a bare field name inside a method), and `CXXThisExpr` (`this`, spelled or implied). The `Counter` struct at lines 108–115 exercises all three.

### `declRefExpr(Matcher<DeclRefExpr>...)` — Matcher<Stmt>

Matches an expression that names a declaration: a variable, function, enumerator or static member. Bare `declRefExpr()` matches 150 in the sample. Narrowing with `to(…)` (Part 6) picks the references to one variable.

```text
clang-query> match declRefExpr(to(varDecl(hasName("cnt"))))
```

**Expected:** 2 matches — the `cnt` in `cnt.count` at `stmts.cpp:115:39` and in `cnt.get()` at `115:51`.

### `memberExpr(Matcher<MemberExpr>...)` — Matcher<Stmt>

Matches member access — `cnt.count`, `this->count`, and a bare `count` inside a method (which is `this->count` in disguise). The static member `total` at line 112 is a `DeclRefExpr`, not a `MemberExpr`, because no object is involved. Bare `memberExpr()` matches 56 in the sample.

```text
clang-query> match memberExpr(hasAncestor(cxxRecordDecl(hasName("Counter"))))
```

**Expected:** 2 matches — the implicit `this->count` at `stmts.cpp:111:22` and the explicit `this->count` at `112:23`.

Outside the class, both the field read and the method call start with a `MemberExpr` on `cnt`.

```text
clang-query> match memberExpr(hasAncestor(functionDecl(hasName("useCounter"))))
```

**Expected:** 2 matches — `cnt.count` at `stmts.cpp:115:39` and `cnt.get` at `115:51`.

### `cxxThisExpr(Matcher<CXXThisExpr>...)` — Matcher<Stmt>

Matches `this`, whether you wrote it or Clang inserted it for a bare member name. Bare `cxxThisExpr()` matches 13 in the sample — the stubs and the `Vec2` operators use members too.

```text
clang-query> match cxxThisExpr(hasAncestor(cxxRecordDecl(hasName("Counter"))))
```

**Expected:** 2 matches — the implicit `this` in `return count;` at `stmts.cpp:111:22` and the explicit one at `112:23`.

---

## 3.4 — Operators

Built-in operators are `UnaryOperator`, `BinaryOperator` and `ConditionalOperator` nodes. An *overloaded* operator on a class type is a call in disguise (`CXXOperatorCallExpr`), and a comparison rewritten through `<=>` is a `CXXRewrittenBinaryOperator`. `sizeof`/`alignof`, subscripts, parentheses, fold expressions and `noexcept(…)` each get their own node. The `operators` function at lines 125–138 has one of each.

### `unaryOperator(Matcher<UnaryOperator>...)` — Matcher<Stmt>

Matches a built-in prefix or postfix operator: `-a`, `!a`, `++k`, `*p`, `&x`. Bare `unaryOperator()` also finds the `++k`/`--i` in the loops and the `-1` in the `strong_ordering` stub.

```text
clang-query> match unaryOperator(hasAncestor(functionDecl(hasName("operators"))))
```

**Expected:** 1 match — `-a` at `stmts.cpp:126:13`.

### `binaryOperator(Matcher<BinaryOperator>...)` — Matcher<Stmt>

Matches a built-in binary operator, including assignment and compound assignment. `hasOperatorName` (Part 6) picks one spelling.

```text
clang-query> match binaryOperator(hasOperatorName("*"))
```

**Expected:** 3 matches — `v * 1024` at `stmts.cpp:82:75`, `a * b` at `127:14`, `(a + b) * 2` at `135:13`.

### `conditionalOperator(Matcher<ConditionalOperator>...)` — Matcher<Stmt>

Matches the three-operand `cond ? x : y`.

```text
clang-query> match conditionalOperator()
```

**Expected:** 1 match — `a ? b : neg` at `stmts.cpp:128:14`.

### `binaryConditionalOperator(Matcher<BinaryConditionalOperator>...)` — Matcher<Stmt>

Matches the GNU two-operand form `a ?: b`, which yields `a` if it is true and `b` otherwise, evaluating `a` once. The single evaluation is modelled with an `OpaqueValueExpr` (section 3.7).

```text
clang-query> match binaryConditionalOperator()
```

**Expected:** 1 match — `a ?: b` at `stmts.cpp:129:15`.

### `cxxOperatorCallExpr(Matcher<CXXOperatorCallExpr>...)` — Matcher<Stmt>

Matches a call to an *overloaded* operator — `v + w` on a class type is really `v.operator+(w)`. A built-in `a * b` on ints never matches; use `binaryOperator` for that. The rewritten `v < w` at line 132 contributes two calls: the `operator<=>` and the `operator<` on the resulting `strong_ordering`.

```text
clang-query> match cxxOperatorCallExpr(hasAncestor(functionDecl(hasName("operators"))))
```

**Expected:** 3 matches — `v + w` at `stmts.cpp:131:15`, and the `<=>` and `< 0` calls inside `v < w` (both at `132:13`).

### `cxxRewrittenBinaryOperator(Matcher<CXXRewrittenBinaryOperator>...)` — Matcher<Stmt>

Matches a C++20 comparison that Clang rewrote in terms of `operator<=>` or `operator==`: `v < w` becomes `(v <=> w) < 0`. The node keeps the original spelling and hangs the rewritten call tree beneath it. Bare `cxxRewrittenBinaryOperator()` matches 3 — two more are synthesized inside the defaulted `operator<=>` at line 121.

```text
clang-query> match cxxRewrittenBinaryOperator(hasAncestor(functionDecl(hasName("operators"))))
```

**Expected:** 1 match — `v < w` at `stmts.cpp:132:13`.

### `unaryExprOrTypeTraitExpr(Matcher<UnaryExprOrTypeTraitExpr>...)` — Matcher<Stmt>

Matches `sizeof`, `alignof`, `__alignof`, `vec_step` and friends, whether the operand is an expression or a type.

```text
clang-query> match unaryExprOrTypeTraitExpr()
```

**Expected:** 2 matches — `sizeof(a)` at `stmts.cpp:133:22` and `alignof(int)` at `133:34`.

### `arraySubscriptExpr(Matcher<ArraySubscriptExpr>...)` — Matcher<Stmt>

Matches a built-in `base[index]`. Bare `arraySubscriptExpr()` matches 8 in the sample, most of them inside implicit array-copy loops (section 3.7), so narrow by function.

```text
clang-query> match arraySubscriptExpr(hasAncestor(functionDecl(hasName("operators"))))
```

**Expected:** 1 match — `arr[1]` at `stmts.cpp:134:14`.

### `parenExpr(Matcher<ParenExpr>...)` — Matcher<Stmt>

Matches parentheses that group an expression. Parentheses belonging to a call or a declarator are syntax, not nodes — but the `(a)` in `sizeof(a)` *is* a `ParenExpr`, because `sizeof` takes an expression operand and you parenthesized it. `alignof(int)` has a type operand and no paren node.

```text
clang-query> match parenExpr()
```

**Expected:** 2 matches — the `(a)` of `sizeof(a)` at `stmts.cpp:133:28` and `(a + b)` at `135:13`.

### `cxxFoldExpr(Matcher<CXXFoldExpr>...)` — Matcher<Stmt>

Matches a C++17 fold expression over a parameter pack such as `(0 + ... + args)`. The node exists only in the template pattern; an instantiation replaces it with ordinary binary operators.

```text
clang-query> match cxxFoldExpr()
```

**Expected:** 1 match — `(0 + ... + args)` at `stmts.cpp:124:61`.

### `cxxNoexceptExpr(Matcher<CXXNoexceptExpr>...)` — Matcher<Stmt>

Matches the `noexcept(expr)` *operator*, which yields a `bool`. It does not match the `noexcept` *specifier* on a function declaration — `bool nothrow() noexcept;` at line 123 is not a hit.

```text
clang-query> match cxxNoexceptExpr()
```

**Expected:** 1 match — `noexcept(nothrow())` at `stmts.cpp:136:13`.

---

## 3.5 — Calls, construction and lambdas

`CallExpr` is the base for every call; `CXXMemberCallExpr` narrows to `obj.method()`. Constructing an object is not a call in Clang's eyes — it is a `CXXConstructExpr`, and `Type(args)` written like a cast is a `CXXTemporaryObjectExpr`. `new`, `delete` and lambda expressions get their own nodes. The `calls` function at lines 147–156 has one of each.

### `callExpr(Matcher<CallExpr>...)` — Matcher<Stmt>

Matches any call: free function, member function, overloaded operator, user-defined literal, or a call through a function pointer or lambda. It does *not* match constructor calls. Bare `callExpr()` matches 62 in the sample (the coroutine machinery alone adds dozens of implicit calls).

```text
clang-query> match callExpr(hasAncestor(functionDecl(hasName("calls"))))
```

**Expected:** 4 matches — `w.draw()` at `stmts.cpp:150:3`, `withDefault(42)` at `151:3`, `bar()` inside the lambda at `154:29`, `lam()` at `155:10`.

### `cxxMemberCallExpr(Matcher<CXXMemberCallExpr>...)` — Matcher<Stmt>

Matches a call through a member function — `w.draw()`, `p->size()`. A call to a static member through an object also counts; a call to an overloaded operator does not (that is `cxxOperatorCallExpr`). Bare `cxxMemberCallExpr()` matches 26 in the sample, mostly implicit coroutine calls.

```text
clang-query> match cxxMemberCallExpr(hasAncestor(functionDecl(hasName("calls"))))
```

**Expected:** 1 match — `w.draw()` at `stmts.cpp:150:3`.

### `cxxConstructExpr(Matcher<CXXConstructExpr>...)` — Matcher<Stmt>

Matches a constructor invocation, explicit or implicit: `Widget w(1, 2)`, the temporary in `Widget(3, 4)`, the construction inside `new Widget`, and implicit copies made when passing by value. Bare `cxxConstructExpr()` matches 17 in the sample.

```text
clang-query> match cxxConstructExpr(hasAncestor(functionDecl(hasName("calls"))))
```

**Expected:** 3 matches — `w(1, 2)` at `stmts.cpp:148:10`, `Widget(3, 4)` at `149:16`, the construction inside `new Widget` at `152:22`.

### `cxxTemporaryObjectExpr(Matcher<CXXTemporaryObjectExpr>...)` — Matcher<Stmt>

Matches a functional-notation construction with zero or two-plus arguments — `Widget(3, 4)` or `Widget()`. With exactly one argument, `Widget(x)` is a `CXXFunctionalCastExpr` instead (section 3.6). This node is a subclass of `CXXConstructExpr`, so it is one of the three matches above.

```text
clang-query> match cxxTemporaryObjectExpr()
```

**Expected:** 1 match — `Widget(3, 4)` at `stmts.cpp:149:16`.

### `cxxDefaultArgExpr(Matcher<CXXDefaultArgExpr>...)` — Matcher<Stmt>

Matches the placeholder Clang inserts at a call site for an argument you left out: in `withDefault(42)` the second argument is a `CXXDefaultArgExpr` that refers back to `y = 0`. The node has no source range of its own, so clang-query reports the match without a code snippet.

```text
clang-query> match cxxDefaultArgExpr()
```

**Expected:** 1 match — the omitted `y` argument of `withDefault(42)` at `stmts.cpp:151:3` (printed without a location).

### `cxxNewExpr(Matcher<CXXNewExpr>...)` — Matcher<Stmt>

Matches a `new` expression, including placement and array forms.

```text
clang-query> match cxxNewExpr()
```

**Expected:** 1 match — `new Widget` at `stmts.cpp:152:18`.

### `cxxDeleteExpr(Matcher<CXXDeleteExpr>...)` — Matcher<Stmt>

Matches a `delete` or `delete[]` expression.

```text
clang-query> match cxxDeleteExpr()
```

**Expected:** 1 match — `delete heap` at `stmts.cpp:153:3`.

### `lambdaExpr(Matcher<LambdaExpr>...)` — Matcher<Stmt>

Matches a lambda expression. Behind the node Clang builds an anonymous class with an `operator()`, so the lambda body is also reachable through `cxxRecordDecl` and `cxxMethodDecl` (Part 2). The sample has two lambdas: one capturing by reference in `calls`, one capturing an array by value in `arrays`.

```text
clang-query> match lambdaExpr()
```

**Expected:** 2 matches — `[&]() { return bar(); }` at `stmts.cpp:154:14` and `[pair]() { … }` at `187:14`.

---

## 3.6 — Casts

Clang uses "cast" for every conversion, written or not. `CastExpr` is the base; below it `ImplicitCastExpr` covers the conversions the compiler inserts (lvalue-to-rvalue, integral promotion, array-to-pointer, derived-to-base …) and `ExplicitCastExpr` covers the ones you spell out: C-style `(int)x`, functional `long(8)`, and the four keyword casts, which share the base `CXXNamedCastExpr`. The `casts` function at lines 161–169 has one of each.

```
CastExpr
├── ImplicitCastExpr
└── ExplicitCastExpr
    ├── CStyleCastExpr          (int)2.2f
    ├── CXXFunctionalCastExpr   long(8)
    └── CXXNamedCastExpr
        ├── CXXStaticCastExpr   static_cast<long>(8)
        ├── CXXDynamicCastExpr  dynamic_cast<Derived *>(&base)
        ├── CXXReinterpretCastExpr
        └── CXXConstCastExpr
```

### `castExpr(Matcher<CastExpr>...)` — Matcher<Stmt>

Matches every cast node, implicit or explicit. Bare `castExpr()` matches 173 in the sample. Even the short `casts` function has eleven: six you wrote and five Clang added (for example the `float`-to-`int` conversion *inside* `(int)2.2f` is a separate `ImplicitCastExpr` child of the C-style cast).

```text
clang-query> match castExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 11 matches — the six explicit casts at `stmts.cpp:162:19`, `163:21`, `164:15`, `165:18`, `166:16`, `167:14`, plus implicit ones at `162:24`, `163:26`, `164:33` and two at `168:19`.

### `implicitCastExpr(Matcher<ImplicitCastExpr>...)` — Matcher<Stmt>

Matches only the casts Clang inserted. `long implicit = truncated;` at line 168 needs two: lvalue-to-rvalue to read `truncated`, then integral conversion `int` → `long`. Bare `implicitCastExpr()` matches 162 in the sample — most of the 173 casts are implicit.

```text
clang-query> match implicitCastExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 5 matches — the inner conversions of the literal casts at `stmts.cpp:162:24`, `163:26`, `164:33`, and the two casts of `truncated` at `168:19`.

### `explicitCastExpr(Matcher<ExplicitCastExpr>...)` — Matcher<Stmt>

Matches a cast written in source — C-style, functional or keyword. It never matches an implicit conversion, so the six here are exactly the six lines you can see.

```text
clang-query> match explicitCastExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 6 matches — `stmts.cpp:162:19`, `163:21`, `164:15`, `165:18`, `166:16`, `167:14`.

### `cStyleCastExpr(Matcher<CStyleCastExpr>...)` — Matcher<Stmt>

Matches a C-style cast `(Type)expr`. The sample also has one in `exotic` at line 246, so we narrow.

```text
clang-query> match cStyleCastExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 1 match — `(int)2.2f` at `stmts.cpp:162:19`.

### `cxxFunctionalCastExpr(Matcher<CXXFunctionalCastExpr>...)` — Matcher<Stmt>

Matches a functional-notation cast with exactly one argument: `long(8)`, `Foo(bar)`. With zero or several arguments the same spelling is a `CXXTemporaryObjectExpr` (section 3.5). Bare `cxxFunctionalCastExpr()` also finds two inside the coroutine's `std::suspend_never{}` at line 226.

```text
clang-query> match cxxFunctionalCastExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 1 match — `long(8)` at `stmts.cpp:163:21`.

### `cxxNamedCastExpr(Matcher<CXXNamedCastExpr>...)` — Matcher<Stmt>

Matches any of the four keyword casts — `static_cast`, `dynamic_cast`, `reinterpret_cast`, `const_cast` — through their shared base class.

**Not in clang-query 22** — this name is in the reference but is not registered in the dynamic matcher registry of this build (C++-API-only). The nearest equivalent is an `anyOf` of the four concrete matchers:

```text
clang-query> match stmt(anyOf(cxxStaticCastExpr(), cxxDynamicCastExpr(),
                   cxxReinterpretCastExpr(), cxxConstCastExpr()),
             hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 4 matches — `static_cast` at `stmts.cpp:164:15`, `dynamic_cast` at `165:18`, `reinterpret_cast` at `166:16`, `const_cast` at `167:14`.

### `cxxStaticCastExpr(Matcher<CXXStaticCastExpr>...)` — Matcher<Stmt>

Matches a `static_cast<T>(e)`. Bare `cxxStaticCastExpr()` gives 3 — Clang synthesizes two more inside the defaulted `operator<=>` to convert member comparisons to `std::strong_ordering`.

```text
clang-query> match cxxStaticCastExpr(hasAncestor(functionDecl(hasName("casts"))))
```

**Expected:** 1 match — `static_cast<long>(8)` at `stmts.cpp:164:15`.

### `cxxDynamicCastExpr(Matcher<CXXDynamicCastExpr>...)` — Matcher<Stmt>

Matches a `dynamic_cast<T>(e)`. The source type must be polymorphic, which is why `Base` at line 159 has a virtual destructor.

```text
clang-query> match cxxDynamicCastExpr()
```

**Expected:** 1 match — `dynamic_cast<Derived *>(&base)` at `stmts.cpp:165:18`.

### `cxxReinterpretCastExpr(Matcher<CXXReinterpretCastExpr>...)` — Matcher<Stmt>

Matches a `reinterpret_cast<T>(e)`.

```text
clang-query> match cxxReinterpretCastExpr()
```

**Expected:** 1 match — `reinterpret_cast<char *>(&truncated)` at `stmts.cpp:166:16`.

### `cxxConstCastExpr(Matcher<CXXConstCastExpr>...)` — Matcher<Stmt>

Matches a `const_cast<T>(e)`.

```text
clang-query> match cxxConstCastExpr()
```

**Expected:** 1 match — `const_cast<int *>(&cref)` at `stmts.cpp:167:14`.

---

## 3.7 — Invisible nodes: temporaries, cleanups and helpers

These nodes have no keyword. Clang adds them to make object lifetime, evaluation order and initialization explicit in the tree. You will meet them constantly when a matcher "should" hit but does not — a `has(callExpr())` fails because an `ExprWithCleanups` sits in between. Lines 172–190 of the sample provide the temporaries and array copies; the `?:` at line 129 and the `case 37:` at line 66 provide the rest.

```
take(make());                 // line 180, as Clang sees it:
ExprWithCleanups              ← "run destructors at the end of this full-expression"
└── CallExpr take
    └── CXXBindTemporaryExpr  ← "this temporary has a destructor to run"
        └── CallExpr make
```

### `exprWithCleanups(Matcher<ExprWithCleanups>...)` — Matcher<Stmt>

Matches the wrapper Clang places around a full-expression that created temporaries with non-trivial destructors, marking where those destructors run. Bare `exprWithCleanups()` matches 11 in the sample — the coroutine and the `initializer_list` also create temporaries.

```text
clang-query> match exprWithCleanups(hasAncestor(functionDecl(hasName("temporaries"))))
```

**Expected:** 2 matches — around `take(make())` at `stmts.cpp:180:3` and around `make().size()` at `181:11`.

### `cxxBindTemporaryExpr(Matcher<CXXBindTemporaryExpr>...)` — Matcher<Stmt>

Matches the node that binds a temporary of class type with a non-trivial destructor, so the destructor can be scheduled. A temporary of a trivially destructible type (an `int`, a `Point`) never gets one.

```text
clang-query> match cxxBindTemporaryExpr()
```

**Expected:** 2 matches — the `make()` temporary passed to `take` at `stmts.cpp:180:8` and the one in `make().size()` at `181:11`.

### `materializeTemporaryExpr(Matcher<MaterializeTemporaryExpr>...)` — Matcher<Stmt>

Matches the point where a prvalue is turned into a real object with an address — needed when you call a member function on it, bind it to a reference, or take a member of it. `take(make())` does not need one (the prvalue initializes the parameter directly); `make().size()` does. Bare `materializeTemporaryExpr()` matches 6 in the sample.

```text
clang-query> match materializeTemporaryExpr(hasAncestor(functionDecl(hasName("temporaries"))))
```

**Expected:** 1 match — the `make()` temporary in `make().size()` at `stmts.cpp:181:11`.

### `implicitValueInitExpr(Matcher<ImplicitValueInitExpr>...)` — Matcher<Stmt>

Matches the value-initialization Clang adds for members an initializer list left out: `Point half = {5};` at line 100 has an `ImplicitValueInitExpr` for `y` in its semantic form. The node has no source location, so the match is printed without a snippet. Bare `implicitValueInitExpr()` matches 2 — `Grid g1{}` at line 188 supplies the other.

```text
clang-query> match implicitValueInitExpr(hasAncestor(functionDecl(hasName("literals"))))
```

**Expected:** 1 match — the implicit `y = 0` of `Point half = {5}` at `stmts.cpp:100` (printed without a location).

### `arrayInitLoopExpr(Matcher<ArrayInitLoopExpr>...)` — Matcher<Stmt>

Matches the implicit element-by-element loop Clang uses to copy an array in three places: the implicit copy/move constructor of a class with an array member, a lambda that captures an array by value, and a structured binding that decomposes an array. The sample has all three.

```text
clang-query> match arrayInitLoopExpr()
```

**Expected:** 3 matches — the copy of `cells` in `Grid`'s implicit copy constructor at `stmts.cpp:183:8`, the copy of `pair` for `auto [first, second]` at `186:26`, the capture `[pair]` at `187:15`.

### `arrayInitIndexExpr(Matcher<ArrayInitIndexExpr>...)` — Matcher<Stmt>

Matches the current-index placeholder inside an `ArrayInitLoopExpr` — the `i` of the implicit `dst[i] = src[i]`. One per loop, and like the loop itself it has no source location.

```text
clang-query> match arrayInitIndexExpr()
```

**Expected:** 3 matches — one index for each of the three array-copy loops above (printed without locations).

### `opaqueValueExpr(Matcher<OpaqueValueExpr>...)` — Matcher<Stmt>

Matches a placeholder that stands for an already-evaluated subexpression so it can be referenced twice without being evaluated twice. The GNU `a ?: b` uses one for `a` (it is both the condition and the result); array-copy loops and coroutine awaits use them as well. Bare `opaqueValueExpr()` matches 20 in the sample.

```text
clang-query> match opaqueValueExpr(hasAncestor(functionDecl(hasName("operators"))))
```

**Expected:** 2 matches — the two references to the shared `a` in `a ?: b` at `stmts.cpp:129:15`.

### `constantExpr(Matcher<ConstantExpr>...)` — Matcher<Stmt>

Matches a wrapper that marks a subexpression as a constant expression evaluated at compile time — a `case` value, a template argument, the condition of `__builtin_choose_expr`, a `consteval` call. The wrapper caches the evaluated value.

```text
clang-query> match constantExpr()
```

**Expected:** 3 matches — the `37` of `case 37:` at `stmts.cpp:66:8`, the `42` in `Fixed<42>` at `194:24`, the `1` in `__builtin_choose_expr(1, …)` at `241:38`.

---

## 3.8 — Dependent and template nodes

Inside a template, anything that depends on a template parameter cannot be resolved until instantiation. Clang represents each such construct with a "dependent" or "unresolved" node that records what was written and resolves later. The `Dep` template at lines 200–211 has one of each; `Fixed<42>` at line 194 shows what an instantiated non-type parameter looks like.

### `cxxDependentScopeMemberExpr(Matcher<CXXDependentScopeMemberExpr>...)` — Matcher<Stmt>

Matches a member access whose base has a dependent type: `t.go()` where `t` is a `T`. Bare `cxxDependentScopeMemberExpr()` matches 6 — the dependent `co_await` at line 231 generates five more for `await_ready`/`await_suspend`/`await_resume` lookups.

```text
clang-query> match cxxDependentScopeMemberExpr(hasAncestor(functionDecl(hasName("run"))))
```

**Expected:** 1 match — `t.go` at `stmts.cpp:203:5`.

### `dependentScopeDeclRefExpr(Matcher<DependentScopeDeclRefExpr>...)` — Matcher<Stmt>

Matches a qualified name whose scope is dependent: `T::value`.

```text
clang-query> match dependentScopeDeclRefExpr()
```

**Expected:** 1 match — `T::value` at `stmts.cpp:204:5`.

### `unresolvedLookupExpr(Matcher<UnresolvedLookupExpr>...)` — Matcher<Stmt>

Matches a name that lookup found but could not pin to one declaration because the arguments are dependent — typically a call to a function template with a dependent argument. The sample has two: `make_one<T>` in `Dep::run` and the implicit `operator co_await` lookup for the dependent await at line 231.

```text
clang-query> match unresolvedLookupExpr()
```

**Expected:** 2 matches — `make_one<T>` at `stmts.cpp:205:5` and the operator lookup for `co_await awaitable` at `231:3`.

### `unresolvedMemberExpr(Matcher<UnresolvedMemberExpr>...)` — Matcher<Stmt>

Matches a member access on a *known* class whose member is a template with dependent arguments: `api.call<T>` where `Api::call` is a member template. Compare `cxxDependentScopeMemberExpr`, where the *base* is dependent.

```text
clang-query> match unresolvedMemberExpr()
```

**Expected:** 1 match — `api.call<T>` at `stmts.cpp:207:5`.

### `cxxUnresolvedConstructExpr(Matcher<CXXUnresolvedConstructExpr>...)` — Matcher<Stmt>

Matches a functional-notation construction of a dependent type: `T(t)`. After instantiation it becomes a `CXXConstructExpr` or a `CXXFunctionalCastExpr`.

```text
clang-query> match cxxUnresolvedConstructExpr()
```

**Expected:** 1 match — `T(t)` at `stmts.cpp:208:14`.

### `substNonTypeTemplateParmExpr(Matcher<SubstNonTypeTemplateParmExpr>...)` — Matcher<Stmt>

Matches the node that records "this `42` used to be the parameter `N`" in an instantiation. `Fixed<42>` instantiates `static const int n = N;`, and the `N` on the right-hand side becomes a `SubstNonTypeTemplateParmExpr` wrapping the literal `42`. It only exists in instantiations, never in the template pattern.

```text
clang-query> match substNonTypeTemplateParmExpr()
```

**Expected:** 1 match — the substituted `N` in `Fixed<42>` at `stmts.cpp:193:54`.

### `parenListExpr(Matcher<ParenListExpr>...)` — Matcher<Stmt>

Matches a parenthesized initializer list that has not been given a type yet — the `(*this)` in `Dep self(*this);` inside a template, where `*this` is dependent so the constructor call cannot be chosen. A parenthesized comma expression like `(a, b)` is a `ParenExpr`, not this. Bare `parenListExpr()` matches 2 — the other is a member initializer in the `initializer_list` stub.

```text
clang-query> match parenListExpr(hasAncestor(functionDecl(hasName("run"))))
```

**Expected:** 1 match — `(*this)` at `stmts.cpp:209:13`.

### `requiresExpr(Matcher<RequiresExpr>...)` — Matcher<Expr>

Matches a C++20 `requires (T p) { *p; }` expression — the body of a concept or a trailing requires-clause. The sample's `Dereferencable` concept at line 212 contains one.

**Not in clang-query 22** — the matcher is in the reference but is not registered in this build's dynamic registry (C++-API-only). You can still reach the concept itself through its declaration matcher (Part 2), and the expressions inside the requirement body are ordinary nodes:

```text
clang-query> match conceptDecl(hasName("Dereferencable"))
```

**Expected:** 1 match — `concept Dereferencable` at `stmts.cpp:212:1`.

---

## 3.9 — Coroutines

A coroutine function's body is wrapped in a `CoroutineBodyStmt` that also owns the implicit `initial_suspend()` and `final_suspend()` awaits, the promise construction and the fall-through `co_return`. `co_await`, `co_yield` and `co_return` are their own nodes; a `co_await` on a dependent operand inside a template is a `DependentCoawaitExpr`. The `coro` function at lines 225–229 uses all three keywords; `depCoro` at line 230 is the template case.

### `coroutineBodyStmt(Matcher<CoroutineBodyStmt>...)` — Matcher<Stmt>

Matches the wrapper around a coroutine's body. It exists for every function that uses a coroutine keyword, including the template one.

```text
clang-query> match coroutineBodyStmt()
```

**Expected:** 2 matches — the body of `coro` at `stmts.cpp:225:13` and of `depCoro` at `230:46`.

### `coawaitExpr(Matcher<CoawaitExpr>...)` — Matcher<Stmt>

Matches a resolved `co_await` — the one you wrote *and* the two implicit ones on `initial_suspend()` and `final_suspend()` that every coroutine gets. Bare `coawaitExpr()` matches 5 (the template `depCoro` contributes its two implicit awaits too).

```text
clang-query> match coawaitExpr(hasAncestor(functionDecl(hasName("coro"))))
```

**Expected:** 3 matches — `co_await std::suspend_never{}` at `stmts.cpp:226:3` and the implicit initial/final awaits (both reported at `225:6`).

### `coyieldExpr(Matcher<CoyieldExpr>...)` — Matcher<Stmt>

Matches `co_yield value`, which is sugar for `co_await promise.yield_value(value)`.

```text
clang-query> match coyieldExpr()
```

**Expected:** 1 match — `co_yield 1` at `stmts.cpp:227:3`.

### `coreturnStmt(Matcher<CoreturnStmt>...)` — Matcher<Stmt>

Matches `co_return`. Besides the one you wrote, Clang synthesizes a fall-through `co_return;` for every coroutine whose promise has `return_void()`, so `coro` shows two.

```text
clang-query> match coreturnStmt()
```

**Expected:** 2 matches — the written `co_return;` at `stmts.cpp:228:3` and the implicit fall-through one at `225:6`.

### `dependentCoawaitExpr(Matcher<DependentCoawaitExpr>...)` — Matcher<Stmt>

Matches a `co_await` whose operand is type-dependent, so the awaiter cannot be resolved until instantiation.

```text
clang-query> match dependentCoawaitExpr()
```

**Expected:** 1 match — `co_await awaitable` at `stmts.cpp:231:3`.

---

## 3.10 — Exotic C and GNU extensions

The last group is Clang's support for constructs outside standard C++: GNU statement-expressions, address-of-label, `__builtin_choose_expr`, C11 `_Generic`, vector conversions, atomic builtins, inline `asm`, `__null` and `__func__`. Each is one node and the `exotic` function at lines 238–247 has one of each.

### `stmtExpr(Matcher<StmtExpr>...)` — Matcher<Stmt>

Matches a GNU statement-expression `({ … })` — a block whose last expression is the value.

```text
clang-query> match stmtExpr()
```

**Expected:** 1 match — `({ int X = 4; X; })` at `stmts.cpp:239:12`.

### `addrLabelExpr(Matcher<AddrLabelExpr>...)` — Matcher<Stmt>

Matches the GNU address-of-label `&&label`, the operand of a computed `goto`.

```text
clang-query> match addrLabelExpr()
```

**Expected:** 1 match — `&&exit_label` at `stmts.cpp:240:14`.

### `chooseExpr(Matcher<ChooseExpr>...)` — Matcher<Stmt>

Matches `__builtin_choose_expr(cond, a, b)`, a compile-time conditional whose unchosen branch is never type-checked for errors.

```text
clang-query> match chooseExpr()
```

**Expected:** 1 match — `__builtin_choose_expr(1, a, se)` at `stmts.cpp:241:16`.

### `genericSelectionExpr(Matcher<GenericSelectionExpr>...)` — Matcher<Stmt>

Matches a C11 `_Generic(ctrl, type: expr, …)` selection, accepted by Clang in C++ as an extension.

```text
clang-query> match genericSelectionExpr()
```

**Expected:** 1 match — `_Generic(fl, int : "int", float : "float")` at `stmts.cpp:242:22`.

### `convertVectorExpr(Matcher<ConvertVectorExpr>...)` — Matcher<Stmt>

Matches `__builtin_convertvector(v, DestVectorType)`, an element-wise conversion between vector types of the same length.

```text
clang-query> match convertVectorExpr()
```

**Expected:** 1 match — `__builtin_convertvector(iv, float4)` at `stmts.cpp:243:15`.

### `atomicExpr(Matcher<AtomicExpr>...)` — Matcher<Stmt>

Matches a call to an atomic builtin: `__atomic_load_n`, `__atomic_store`, `__c11_atomic_fetch_add` and friends. These are not `CallExpr` nodes.

```text
clang-query> match atomicExpr()
```

**Expected:** 1 match — `__atomic_load_n(&shared, __ATOMIC_SEQ_CST)` at `stmts.cpp:244:16`.

### `asmStmt(Matcher<AsmStmt>...)` — Matcher<Stmt>

Matches an inline assembly statement, GCC style (`asm("…")`) or Microsoft style. The assembly text itself is a `StringLiteral` child.

```text
clang-query> match asmStmt()
```

**Expected:** 1 match — `asm volatile("nop")` at `stmts.cpp:72:3`.

### `gnuNullExpr(Matcher<GNUNullExpr>...)` — Matcher<Stmt>

Matches the GNU `__null` keyword — what `NULL` expands to in GCC-compatible C++ headers. Distinct from `nullptr` (`cxxNullPtrLiteralExpr`) and from a literal `0`.

```text
clang-query> match gnuNullExpr()
```

**Expected:** 1 match — `__null` at `stmts.cpp:104:17`.

### `predefinedExpr(Matcher<PredefinedExpr>...)` — Matcher<Stmt>

Matches a predefined identifier such as `__func__`, `__FUNCTION__` or `__PRETTY_FUNCTION__`. The node carries a `StringLiteral` child holding the function name.

```text
clang-query> match predefinedExpr()
```

**Expected:** 1 match — `__func__` at `stmts.cpp:103:20`.

---

## 3.11 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| One hierarchy | `stmt()` on a one-line function returned 6 nodes and `expr()` returned 4; every expression is a statement. |
| Invisible nodes | Casts, cleanups, temporaries, default arguments, array-copy loops and coroutine awaits all matched even though they are not in the source. |
| Narrowing | Bare `integerLiteral()` = 100, `castExpr()` = 173, `stmt()` = 985; a second matcher turns each into a countable answer. |
| Sugar is preserved | Range-for, rewritten `<=>` comparisons, `co_yield` and user-defined literals keep their own node above the desugared tree. |
| Templates | Dependent and unresolved nodes stand in until instantiation; `substNonTypeTemplateParmExpr` shows the substitution afterwards. |
| Extensions | GNU/C11 constructs and fixed-point literals each have a node; some need extra flags or a C sample. |
| Missing matchers | `cxxNamedCastExpr` and `requiresExpr` are absent from clang-query 22; `anyOf` of the four casts and `conceptDecl` are the workarounds. |

**Quiz.** Find every call to `bar` that is made from inside a lambda body — and only those. (Hint: you need a call matcher, a way to say which function is called, and an ancestor test.)

> [!hint]- Hint
> `callExpr(...)` selects calls; `callee(functionDecl(hasName("bar")))` restricts them to calls of `bar`; `hasAncestor(lambdaExpr())` keeps only those inside a lambda. Plain `callExpr(callee(functionDecl(hasName("bar"))))` would also match the call at line 71.

> [!success]- Answer
> `callExpr(callee(functionDecl(hasName("bar"))), hasAncestor(lambdaExpr()))` — 1 match, the `bar()` inside `[&]() { return bar(); }` at `stmts.cpp:154:29`.

---

[← Part 2 — Node Matchers I — Declarations](part_2_node_matchers_decls.md) | [Part 4 — Node Matchers III — Types & TypeLocs →](part_4_node_matchers_types.md)
