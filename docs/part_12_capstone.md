# Part 12 — Capstone — Real Checks in Pure clang-query

[← Part 11 — Objective-C, OpenMP, CUDA & Blocks](part_11_objc_openmp_cuda_blocks.md) | [README →](README.md)

**Sample:** `manifests/capstone.cpp` · flags: `-std=c++23`

## What You'll Learn
- How a clang-tidy check is really just a handful of reference matchers composed with `allOf`/`unless`/`anyOf`
- Building a check in steps: start wide, count, narrow, count again, until only the smells remain
- Where the DSL stops (no type-size or triviality queries) and how to approximate honestly
- Why `has` and `hasDescendant` give different answers on the same class
- Why `equalsBoundNode` compares *declarations*, not source text
- Keeping a check macro-aware with `isExpandedFromMacro` and `isExpansionInMainFile`
- Running whole query scripts with `-f` and choosing between `diag`, `print` and `detailed-ast` output
- Which 14 reference names do not exist in clang-query 22, and what to use instead

## The Big Picture

Every clang-tidy check you have ever run is a matcher expression plus a
callback that prints a diagnostic. This part throws the callback away and
keeps the matcher. You will rebuild nine well-known checks from the reference
matchers you met in Parts 2–11, one composition step at a time, and store each
finished check as a `.query` script under `manifests/queries/`.

The sample is a deliberately "legacy" module: a hand-written `Vec` container,
a `Widget` hierarchy, a `Cursor` with sloppy assignments, some enum switches
and two macros. Every smell carries a `// SMELL:<check>` tag, so you can always
verify a query against `grep SMELL manifests/capstone.cpp`. (The file also
silences the compiler warnings those smells would trigger, with a few
`#pragma clang diagnostic ignored` lines, so clang-query's output is the only
thing you read.)

The working method is always the same:

```text
   reference matcher          count      narrow with            count
   ─────────────────────────  ─────      ─────────────────────  ─────
   implicitCastExpr(...)        9   ──►  unless(cxxNullPtr...)    7    ◄── the smells
   cxxMethodDecl(isOverride())  9   ──►  unless(hasAttr(...))     5   ──►  unless(isImplicit())  3
```

Start with the node kind, look at what you catch, then add one narrowing
matcher per false positive until the count equals the number of `SMELL` tags.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/capstone.cpp -- -std=c++23
```

---

## 12.1 — modernize-use-nullptr

**Concept.** A literal `0` or the `NULL` macro used where a pointer is
expected. Clang records that conversion as an implicit cast of kind
`CK_NullToPointer`, so the check is "find that cast, unless its source is the
`nullptr` keyword". Composes `implicitCastExpr`, `hasCastKind`,
`hasSourceExpression`, `unless`, `cxxNullPtrLiteralExpr`.

**Step 1 — every null-to-pointer conversion.** This also catches the two
`nullptr` uses, which are fine.

```clang-query
match implicitCastExpr(hasCastKind("CK_NullToPointer"))
```

**Expected:** 9 matches — `capstone.cpp:24`, `:46`, `:50`, `:51`, `:52`, `:53`, `:54`, `:56` and `:193` (inside the `CHECK` macro).

**Step 2 — drop the `nullptr` keyword.** The cast's source expression must not
be a `cxxNullPtrLiteralExpr`. Lines 51 and 54 disappear.

```clang-query
match implicitCastExpr(hasCastKind("CK_NullToPointer"),
                       hasSourceExpression(unless(cxxNullPtrLiteralExpr())))
```

**Expected:** 7 matches — `capstone.cpp:24`, `:46`, `:50`, `:52`, `:53`, `:56`, `:193`, exactly the seven `SMELL:nullptr` tags.

**Step 3 — only the `NULL` spelling.** Narrowing the source expression to a
literal expanded from the `NULL` macro separates the macro uses from plain
`0`s. Useful when the fix-it would have to touch a macro definition instead.

```clang-query
match implicitCastExpr(hasCastKind("CK_NullToPointer"),
                       hasSourceExpression(integerLiteral(isExpandedFromMacro("NULL"))))
```

**Expected:** 4 matches — `capstone.cpp:24`, `:50`, `:56`, `:193`.

**Final script** — `manifests/queries/use-nullptr.query`:

```clang-query
let notNullptr hasSourceExpression(unless(cxxNullPtrLiteralExpr()))
let nullConst implicitCastExpr(hasCastKind("CK_NullToPointer"), notNullptr)
match nullConst.bind("null")
```

**Expected:** 7 matches — the same seven casts as Step 2.

---

## 12.2 — modernize-use-override

**Concept.** A method that overrides a virtual base method but is not spelled
with `override` (or `final`, which implies it). Composes `cxxMethodDecl`,
`isOverride`, `hasAttr`, `anyOf`, `unless`, `isImplicit`. The attribute names
that clang-query 22 accepts are the `attr::` enumerators: `attr::Override`
and `attr::Final`.

**Step 1 — everything that overrides.** Note the surprise at `:79:7`: the
*implicit* destructor of `Label` overrides `~Button`, and `Polygon::area`
at `:94` is included too.

```clang-query
match cxxMethodDecl(isOverride())
```

**Expected:** 9 matches — `capstone.cpp:72`, `:73`, `:74`, `:75`, `:76`, `:81`, `:82`, `:94` and the implicit `~Label` at `:79`.

**Step 2 — drop those spelled `override`.** Five remain, but two of them are
not smells: `id()` at `:75` says `final`, and `~Label` is compiler-generated.

```clang-query
match cxxMethodDecl(isOverride(), unless(hasAttr("attr::Override")))
```

**Expected:** 5 matches — `capstone.cpp:72`, `:74`, `:75`, `:81` and the implicit `~Label` at `:79`.

**Step 3 — accept `final`, ignore implicit methods.** Exactly the three
`SMELL:override` tags remain.

```clang-query
match cxxMethodDecl(isOverride(),
                    unless(anyOf(hasAttr("attr::Override"), hasAttr("attr::Final"))),
                    unless(isImplicit()))
```

**Expected:** 3 matches — `~Button` at `capstone.cpp:72`, `Button::resize` at `:74`, `Label::draw` at `:81`.

**Final script** — `manifests/queries/use-override.query`:

```clang-query
let marked anyOf(hasAttr("attr::Override"), hasAttr("attr::Final"))
let handWritten unless(isImplicit())
match cxxMethodDecl(isOverride(), unless(marked), handWritten).bind("method")
```

**Expected:** 3 matches — `capstone.cpp:72`, `:74`, `:81`.

---

## 12.3 — readability-container-size-empty

**Concept.** `v.size() == 0` (or `0 == v.size()`, `!= 0`, `> 0`) on a class
that offers `empty()`. Composes `binaryOperator`, `hasAnyOperatorName`,
`hasEitherOperand`, `ignoringImpCasts`, `integerLiteral`, `equals`,
`cxxMemberCallExpr`, `callee`, `ofClass`, `hasMethod`.

**Step 1 — every `size()` call.** Ten, including the two on `Counter`, which
has no `empty()`.

```clang-query
match cxxMemberCallExpr(callee(cxxMethodDecl(hasName("size"))))
```

**Expected:** 10 matches — `capstone.cpp:44`, `:104`–`:107`, `:109`, `:110`, `:139`, `:152`, `:192`.

**Step 2 — only classes that also have `empty()`.** `ofClass` narrows on the
method's class; the two `Counter` calls at `:109` and `:152` drop out.

```clang-query
match cxxMemberCallExpr(callee(cxxMethodDecl(hasName("size"),
                                             ofClass(hasMethod(hasName("empty"))))))
```

**Expected:** 8 matches — `capstone.cpp:44`, `:104`–`:107`, `:110`, `:139`, `:192`.

**Step 3 — comparisons against zero.** Wrap it in a `binaryOperator` whose
operands are, in either order, that call and the literal `0`. The literal is
promoted to `unsigned`, so `ignoringImpCasts` is needed on both sides.
Line 110 (`== MAX_ITEMS`) is not a zero comparison and stays out.

```clang-query
match binaryOperator(hasAnyOperatorName("==", "!=", ">"),
                     hasEitherOperand(ignoringImpCasts(integerLiteral(equals(0)))),
                     hasEitherOperand(ignoringImpCasts(cxxMemberCallExpr(callee(cxxMethodDecl(
                         hasName("size"), ofClass(hasMethod(hasName("empty")))))))))
```

**Expected:** 4 matches — `capstone.cpp:104`, `:105`, `:106`, `:107`.

**Final script** — `manifests/queries/container-size-empty.query`:

```clang-query
let sizeOfContainer cxxMemberCallExpr(
  callee(cxxMethodDecl(hasName("size"), ofClass(hasMethod(hasName("empty"))))))
let zero ignoringImpCasts(integerLiteral(equals(0)))
match binaryOperator(hasAnyOperatorName("==", "!=", ">"),
                     hasEitherOperand(zero),
                     hasEitherOperand(ignoringImpCasts(sizeOfContainer))).bind("cmp")
```

**Expected:** 4 matches — `capstone.cpp:104`, `:105`, `:106`, `:107`.

---

## 12.4 — bugprone-assignment-in-if-condition & self-assignment

**Concept, part A.** An `if` whose condition *is* an assignment. The
condition is an `int`, so Clang wraps it in an implicit `int → bool` cast,
and the "explicit" variant at `:130` wraps it in parentheses *and* a
comparison. Composes `ifStmt`, `hasCondition`, `ignoringParenImpCasts`,
`binaryOperator`, `isAssignmentOperator`.

**Step 1 — the naive query finds nothing**, because the assignment is never
the direct condition.

```clang-query
match ifStmt(hasCondition(binaryOperator(isAssignmentOperator())))
```

**Expected:** 0 matches — the condition node is an `ImplicitCastExpr`, not the operator.

**Step 2 — look through the cast.** Line 130 is not matched: after the parens
the outermost operator is `!=`, and the `while` at `:131` is not an `if`.

```clang-query
match ifStmt(hasCondition(ignoringParenImpCasts(binaryOperator(isAssignmentOperator()))))
```

**Expected:** 1 match — `capstone.cpp:129`.

**Final script** — `manifests/queries/assignment-in-if-condition.query`:

```clang-query
let assignment ignoringParenImpCasts(binaryOperator(isAssignmentOperator()))
match ifStmt(hasCondition(assignment)).bind("if")
```

**Expected:** 1 match — `capstone.cpp:129`.

**Concept, part B.** `x = x`. The tempting query binds the left operand and
asks whether the right one `equalsBoundNode` it — and finds nothing, because
`equalsBoundNode` compares *AST node identity* and the two operands are two
different `DeclRefExpr` nodes. Compare the *declarations* they refer to
instead. Composes `hasLHS`, `hasRHS`, `declRefExpr`, `to`, `memberExpr`,
`member`, `hasObjectExpression`, `cxxThisExpr`, `equalsBoundNode`.

**Step 1 — the wrong way (node identity).**

```clang-query
match binaryOperator(hasOperatorName("="),
                     hasLHS(expr().bind("lhs")),
                     hasRHS(ignoringImpCasts(expr(equalsBoundNode("lhs")))))
```

**Expected:** 0 matches — the two operand nodes are never the same object.

**Step 2 — same variable on both sides.** Bind the `varDecl` the left side
refers to, then require the right side to refer to that bound declaration.
This is the `pos = pos` at `:120`, where the parameter shadows the field.

```clang-query
match binaryOperator(hasOperatorName("="),
                     hasLHS(declRefExpr(to(varDecl().bind("v")))),
                     hasRHS(ignoringImpCasts(declRefExpr(to(varDecl(equalsBoundNode("v")))))))
```

**Expected:** 1 match — `capstone.cpp:120` (`pos = pos` in `Cursor::reset`).

**Step 3 — same field on both sides.** Binding the `fieldDecl` alone catches
`limit = limit` (`:123`) and `c.pos = c.pos` (`:133`), but it would also flag
`a.x = b.x`. The final script therefore also pins the object: both sides use
`this`, or both sides use the same bound variable.

```clang-query
match binaryOperator(hasOperatorName("="),
                     hasLHS(memberExpr(member(fieldDecl().bind("f")))),
                     hasRHS(ignoringImpCasts(memberExpr(member(fieldDecl(equalsBoundNode("f")))))))
```

**Expected:** 2 matches — `capstone.cpp:123` and `:133`.

**Final script** — `manifests/queries/self-assignment.query`:

```clang-query
let sameVar allOf(hasLHS(declRefExpr(to(varDecl().bind("v")))),
                  hasRHS(ignoringImpCasts(declRefExpr(to(varDecl(equalsBoundNode("v")))))))
let sameThisField allOf(hasLHS(memberExpr(member(fieldDecl().bind("f")), hasObjectExpression(cxxThisExpr()))),
                        hasRHS(ignoringImpCasts(memberExpr(member(fieldDecl(equalsBoundNode("f"))),
                                                           hasObjectExpression(cxxThisExpr())))))
let sameObjField allOf(hasLHS(memberExpr(member(fieldDecl().bind("g")),
                                          hasObjectExpression(ignoringImpCasts(declRefExpr(to(varDecl().bind("o"))))))),
                       hasRHS(ignoringImpCasts(memberExpr(member(fieldDecl(equalsBoundNode("g"))),
                                                          hasObjectExpression(ignoringImpCasts(declRefExpr(to(varDecl(equalsBoundNode("o"))))))))))
match binaryOperator(hasOperatorName("="), anyOf(sameVar, sameThisField, sameObjField)).bind("self")
```

**Expected:** 3 matches — `capstone.cpp:120`, `:123`, `:133`, the three `SMELL:self-assign` tags.

---

## 12.5 — performance-unnecessary-value-param (approximated)

**Concept.** A class that is expensive to copy, passed by value, and never
modified in the body — it should have been `const&`. The real check asks the
`ASTContext` whether the type is trivially copyable and how big it is.
**The DSL cannot ask either question** (there is no `isTriviallyCopyable`
matcher), so we approximate "expensive" with "has a user-written copy
constructor", and "modified" with "a non-const method is called on it, or it
is assigned to". Composes `parmVarDecl`, `hasType`, `cxxRecordDecl`,
`hasMethod`, `cxxConstructorDecl`, `isCopyConstructor`, `hasAnyParameter`,
`hasDescendant`, `cxxMemberCallExpr`, `on`, `equalsBoundNode`, `isConst`,
`cxxOperatorCallExpr`, `hasArgument`.

**Step 1 — every by-value class parameter.** Includes `Counter c` at `:151`,
which is cheap.

```clang-query
match parmVarDecl(hasType(recordDecl()))
```

**Expected:** 4 matches — `capstone.cpp:137`, `:143`, `:147`, `:151`.

**Step 2 — only "heavy" classes.** `Vec` declares its own copy constructor;
`Counter` does not.

```clang-query
match parmVarDecl(hasType(cxxRecordDecl(hasMethod(
                    cxxConstructorDecl(isCopyConstructor(), unless(isImplicit()))))))
```

**Expected:** 3 matches — `v` in `total` (`capstone.cpp:137`), `grow` (`:143`) and `replace` (`:147`).

**Step 3 — the function never mutates it.** Move up to the `functionDecl`,
bind the parameter, and forbid two descendant shapes: a call of a non-const
method *on* that parameter (`v.push(1)` at `:144`), and an `operator=` call
whose first argument is that parameter (`v = src` at `:148`). Note that a
class assignment is a `cxxOperatorCallExpr`, not a `binaryOperator`.

```clang-query
match functionDecl(hasAnyParameter(parmVarDecl(hasType(cxxRecordDecl(hasMethod(
                       cxxConstructorDecl(isCopyConstructor(), unless(isImplicit())))))).bind("p")),
                   unless(hasDescendant(cxxMemberCallExpr(on(declRefExpr(to(equalsBoundNode("p")))),
                                                          callee(cxxMethodDecl(unless(isConst())))))),
                   unless(hasDescendant(cxxOperatorCallExpr(isAssignmentOperator(),
                                                            hasArgument(0, declRefExpr(to(equalsBoundNode("p"))))))))
```

**Expected:** 1 match — `total` at `capstone.cpp:137`.

**Final script** — `manifests/queries/unnecessary-value-param.query`:

```clang-query
let heavy cxxRecordDecl(hasMethod(cxxConstructorDecl(isCopyConstructor(), unless(isImplicit()))))
let heavyParam parmVarDecl(hasType(heavy)).bind("p")
let mutatingCall cxxMemberCallExpr(on(declRefExpr(to(equalsBoundNode("p")))),
                                   callee(cxxMethodDecl(unless(isConst()))))
let assignedTo cxxOperatorCallExpr(isAssignmentOperator(),
                                   hasArgument(0, declRefExpr(to(equalsBoundNode("p")))))
match functionDecl(hasAnyParameter(heavyParam),
                   unless(hasDescendant(mutatingCall)),
                   unless(hasDescendant(assignedTo))).bind("fn")
```

**Expected:** 1 match — `capstone.cpp:137`.

**Limits, stated honestly.** This misses parameters that are moved from,
passed by non-const reference to another function, or whose address is taken;
it also cannot see through templates or judge a class with an implicit but
still costly copy (a class holding a big array). The real check's
`isExpensiveToCopy` helper lives in the C++ API for exactly these reasons.

---

## 12.6 — non-virtual destructor in a polymorphic class

**Concept.** A class with at least one virtual method whose destructor is not
virtual — whether declared non-virtual (`Polygon`) or never declared at all
(`Shape`). Composes `cxxRecordDecl`, `isDefinition`, `has`, `cxxMethodDecl`,
`isVirtual`, `cxxDestructorDecl`, `unless`.

**Step 1 — polymorphic classes.** Six, including `Shape::Inner`, whose only
virtual member is its destructor.

```clang-query
match cxxRecordDecl(isDefinition(), has(cxxMethodDecl(isVirtual())))
```

**Expected:** 6 matches — `Widget` (`capstone.cpp:61`), `Button` (`:70`), `Label` (`:79`), `Shape` (`:85`), `Shape::Inner` (`:87`), `Polygon` (`:92`).

**Step 2 — without a virtual destructor as a direct child.** `Button` and
`Label` are fine because their destructors inherit virtual-ness from
`~Widget`.

```clang-query
match cxxRecordDecl(isDefinition(),
                    has(cxxMethodDecl(isVirtual())),
                    unless(has(cxxDestructorDecl(isVirtual()))))
```

**Expected:** 2 matches — `Shape` at `capstone.cpp:85` and `Polygon` at `:92`.

**`has` vs `hasDescendant` — why it matters here.** Swap both `has` for
`hasDescendant` and `Shape` is *rescued* by the virtual `~Inner` nested inside
it. `has` looks only at the class's own members; `hasDescendant` walks into
nested classes, method bodies, everything. For "does this class declare X",
`has` (or `hasMethod`) is the right tool.

```clang-query
match cxxRecordDecl(isDefinition(),
                    hasDescendant(cxxMethodDecl(isVirtual())),
                    unless(hasDescendant(cxxDestructorDecl(isVirtual()))))
```

**Expected:** 1 match — only `Polygon` at `capstone.cpp:92`; `Shape` is wrongly excused by `~Inner`.

**Final script** — `manifests/queries/non-virtual-destructor.query`:

```clang-query
let polymorphic has(cxxMethodDecl(isVirtual()))
let virtualDtor has(cxxDestructorDecl(isVirtual()))
match cxxRecordDecl(isDefinition(), polymorphic, unless(virtualDtor)).bind("class")
```

**Expected:** 2 matches — `capstone.cpp:85`, `:92`.

---

## 12.7 — missing `default:` in a switch over an enum

**Concept.** A `switch` whose condition has enum type and whose *own* case
list has no `default:`. Composes `switchStmt`, `hasCondition`,
`ignoringImpCasts`, `hasType`, `enumDecl`, `forEachSwitchCase`,
`defaultStmt`, `unless`.

**Step 1 — condition of enum type, naively.** Only the `enum class Mode`
switch at `:169` shows up: unscoped enums are promoted to `int` in the
condition, so the condition node is an implicit cast whose type is `int`.

```clang-query
match switchStmt(hasCondition(hasType(enumType())))
```

**Expected:** 1 match — `capstone.cpp:169`.

**Step 2 — look through the promotion.** Now all three enum switches appear;
`switch (raw)` at `:176` is an `int` and stays out.

```clang-query
match switchStmt(hasCondition(ignoringImpCasts(hasType(enumDecl()))))
```

**Expected:** 3 matches — `capstone.cpp:161`, `:169`, `:180`.

**Step 3 — no `default:` of its own.** `hasDescendant(defaultStmt())` is the
obvious narrowing and it is wrong: the switch at `:180` contains a *nested*
switch with a `default:` at `:182`, which excuses the outer one.

```clang-query
match switchStmt(hasCondition(ignoringImpCasts(hasType(enumDecl()))),
                 unless(hasDescendant(defaultStmt())))
```

**Expected:** 1 match — `capstone.cpp:161` only; `:180` is wrongly excused by the nested `default:`.

`forEachSwitchCase` visits only the labels that belong to *this* switch, so
it is the correct scope.

```clang-query
match switchStmt(hasCondition(ignoringImpCasts(hasType(enumDecl()))),
                 unless(forEachSwitchCase(defaultStmt())))
```

**Expected:** 2 matches — `capstone.cpp:161` and `:180`, the two `SMELL:missing-default` tags.

**Final script** — `manifests/queries/missing-default-in-switch.query`:

```clang-query
let overEnum hasCondition(ignoringImpCasts(hasType(enumDecl())))
let hasDefault forEachSwitchCase(defaultStmt())
match switchStmt(overEnum, unless(hasDefault)).bind("switch")
```

**Expected:** 2 matches — `capstone.cpp:161`, `:180`.

---

## 12.8 — a macro-aware check

**Concept.** Real code is full of macros, and a fix-it that rewrites text
inside a macro expansion is usually wrong. Two narrowing matchers keep a
check honest: `isExpandedFromMacro("NAME")` says whether a node's source
range came out of that macro, and `isExpansionInMainFile()` says whether it
is in the file you asked to analyse rather than a header. Composes those with
`ifStmt`, `integerLiteral`, `callExpr`, `hasDescendant`.

**Step 1 — nodes born from `CHECK`.** The macro expands to an `if`, so both
`CHECK(...)` lines produce an `ifStmt` whose spelling is at `:14`.

```clang-query
match ifStmt(isExpandedFromMacro("CHECK"))
```

**Expected:** 2 matches — the expansions at `capstone.cpp:192` and `:193`.

Negate it to see only hand-written `if`s:

```clang-query
match ifStmt(unless(isExpandedFromMacro("CHECK")))
```

**Expected:** 17 matches — every other `if` in the file, from `capstone.cpp:45` to `:194`.

**Step 2 — where a literal comes from.** Object-like macros work the same way.

```clang-query
match integerLiteral(isExpandedFromMacro("MAX_ITEMS"))
```

**Expected:** 3 matches — `capstone.cpp:110`, `:192`, `:194`.

Combining the two macros: the `CHECK` whose argument mentions `NULL`.

```clang-query
match ifStmt(isExpandedFromMacro("CHECK"),
             hasDescendant(integerLiteral(isExpandedFromMacro("NULL"))))
```

**Expected:** 1 match — `capstone.cpp:193`.

**Step 3 — main file only.** The sample has no headers, so this excludes
nothing here; on a real translation unit it is what stops a check from
reporting the same `<vector>` line ten thousand times.

```clang-query
match ifStmt(isExpansionInMainFile())
```

**Expected:** 19 matches — all 17 hand-written `if`s plus the 2 `CHECK` expansions.

**Final script** — `manifests/queries/macro-aware-nullptr.query`, the
12.1 check made safe: skip hits produced by `CHECK` (the `NULL` at `:193`
sits inside its argument) and anything outside the main file.

```clang-query
let nullConst implicitCastExpr(hasCastKind("CK_NullToPointer"),
                               hasSourceExpression(unless(cxxNullPtrLiteralExpr())))
let fixable allOf(unless(isExpandedFromMacro("CHECK")), isExpansionInMainFile())
match implicitCastExpr(nullConst, fixable).bind("null")
```

**Expected:** 6 matches — `capstone.cpp:24`, `:46`, `:50`, `:52`, `:53`, `:56`; the one at `:193` is dropped.

---

## 12.9 — running scripts with `-f` and reading the output

A `.query` file is just the session transcript without the prompts: `#`
comments, `set` lines, `let` definitions and `match` commands, one per line
or split across lines inside parentheses. Run one with `-f`:

```bash
export LLVM=$(brew --prefix llvm)
$LLVM/bin/clang-query -f manifests/queries/use-override.query manifests/capstone.cpp -- -std=c++23
```

Run every check in one go (each `match` prints its own count):

```bash
for f in manifests/queries/*.query; do
  echo "== $f"
  $LLVM/bin/clang-query -f "$f" manifests/capstone.cpp -- -std=c++23 | grep -E 'match(es)?\.$'
done
```

The script `manifests/queries/all.query` bundles the eight checks into one
session, and its counts (7, 3, 4, 1, 3, 1, 2, 2) are the ones you derived
above.

**Choosing an output mode.** `set output <mode>` replaces the output;
`enable output <mode>` adds one. Three modes matter:

* `diag` — a compiler-style location with a caret for every bound node.
  Best for scripts: it is what a clang-tidy diagnostic looks like, and it
  shows the macro-expansion chain (`expanded from macro 'NULL'`).

```clang-query
set output diag
match ifStmt(isExpandedFromMacro("CHECK"))
```

**Expected:** 2 matches — each reported at its use site (`capstone.cpp:192`, `:193`) *and* at the macro body (`:14`).

* `print` — pretty-prints the bound node's source. Best when you want to
  see the *expression* rather than where it is; for the two `CHECK` hits it
  prints the expanded `if (!(…)) fail_fast()` text.

```clang-query
set output print
match ifStmt(isExpandedFromMacro("CHECK"))
```

**Expected:** 2 matches — printed as the expanded `if` statements, no file locations.

* `detailed-ast` (alias `dump`) — the full `-ast-dump` subtree of each bound
  node. Use it to discover which node kinds and implicit casts you have to
  look through; it is how you would have found the `int → bool` cast in
  12.4 without guessing.

```clang-query
set output detailed-ast
match ifStmt(isExpandedFromMacro("CHECK"))
```

**Expected:** 2 matches — each followed by its `IfStmt` subtree, including the `ImplicitCastExpr <IntegralCast>` around `MAX_ITEMS`.

Two more settings are worth knowing in scripts: `set print-matcher true`
echoes the matcher above each result set (handy when a file has many
`match` lines), and `set bind-root false` suppresses the automatic `root`
binding so that only your own `.bind()` names are printed:

```clang-query
set bind-root false
match cxxRecordDecl(hasName("Shape"), forEachDescendant(cxxRecordDecl(isDefinition()).bind("m")))
```

**Expected:** 1 match — only the `m` binding, `Shape::Inner` at `capstone.cpp:87`; no `root` line.

---

## 12.10 — Appendix: reference names not registered in clang-query 22

`scripts/catalog.json` marks 14 of the 516 reference names
`"in_clang_query_22": false`. Typing any of them gives
`Matcher not found`. They fall into two groups: matchers that exist in the
C++ header but were never added to the dynamic registry that clang-query
uses, and matchers documented on the trunk reference page that are newer than
the 22.1.8 release (not in its headers at all).

| Name | Return type(s) | What it does | Why absent | Nearest clang-query equivalent |
|------|----------------|--------------|------------|--------------------------------|
| `traverse` | `Matcher<*>` | Runs the nested matcher with a given traversal kind (`TK_AsIs` / `TK_IgnoreUnlessSpelledInSource`) | C++-API-only: takes an enum argument the registry does not parse | `set traversal IgnoreUnlessSpelledInSource` for the whole session |
| `findAll` | `Matcher<*>` | Matches the node itself *and* every descendant matching M, one result each | C++-API-only: it is a header-only alias for `eachOf(M, forEachDescendant(M))` | `eachOf(M, forEachDescendant(M))` |
| `equalsNode` | `Matcher<Decl>`, `Matcher<Stmt>`, `Matcher<Type>` | True if the node is pointer-identical to a node you hold in C++ | C++-API-only: takes a raw node pointer, impossible to write in a script | `equalsBoundNode("id")` — compare against a bound node instead |
| `cxxNamedCastExpr` | `Matcher<Stmt>` | Any of the four named casts (`static_cast` …) | C++-API-only: the node matcher was never registered | `explicitCastExpr(unless(anyOf(cStyleCastExpr(), cxxFunctionalCastExpr())))`, or `anyOf` of the four specific cast matchers |
| `functionTypeLoc` | `Matcher<TypeLoc>` | The `TypeLoc` of a function type (`void (int)`) | Newer than 22.1.8: not in the installed headers | `typeLoc(loc(functionType()))` |
| `isInheritingConstructor` | `Matcher<CXXConstructorDecl>` | A constructor brought in by `using Base::Base;` | C++-API-only: present in the header, missing from the registry | `usingDecl(hasAnyUsingShadowDecl(hasTargetDecl(cxxConstructorDecl())))` to find the `using` that introduces them |
| `requiresExpr` | `Matcher<Expr>` | A `requires (…) { … }` expression | C++-API-only: present in the header, missing from the registry | `expr()` narrowed by `hasParent(conceptDecl())` / `conceptDecl(hasDescendant(expr()))`; there is no exact stand-in |
| `requiresExprBodyDecl` | `Matcher<Decl>` | The body `{ … }` of a requires-expression | C++-API-only: present in the header, missing from the registry | none; match the enclosing `conceptDecl` |
| `templateArgumentLocCountIs` | `Matcher<ClassTemplateSpecializationDecl>`, `Matcher<DeclRefExpr>`, `Matcher<FunctionDecl>`, `Matcher<OverloadExpr>`, `Matcher<TemplateSpecializationTypeLoc>`, `Matcher<VarTemplateSpecializationDecl>` | Exactly N *written* template arguments | Newer than 22.1.8: not in the installed headers | `templateArgumentCountIs(N)` (counts *all* arguments, including defaulted ones) |
| `ompCountsClause` | `Matcher<OMPClause>` | The `counts(…)` clause of `#pragma omp split` | Newer than 22.1.8 (OpenMP 6 loop transformations) | none; `ompExecutableDirective(hasAnyClause(anything()))` then read the dump to see the clauses |
| `ompFromClause` | `Matcher<OMPClause>` | `from(a)` on `#pragma omp target update` | Newer than 22.1.8 | none; see above |
| `ompSplitDirective` | `Matcher<Stmt>` | `#pragma omp split` | Newer than 22.1.8 | `ompExecutableDirective()` and read the dump |
| `ompTargetUpdateDirective` | `Matcher<Stmt>` | `#pragma omp target update` | Newer than 22.1.8 | `ompExecutableDirective()` and read the dump |
| `ompToClause` | `Matcher<OMPClause>` | `to(a)` on `#pragma omp target update` | Newer than 22.1.8 | none; see above |

Three of the substitutes are worth running on the capstone sample.

**`traverse` → `set traversal`.** In the default `AsIs` mode an initializer
like `unsigned sum = 0;` is an `ImplicitCastExpr` around the literal, so the
naive matcher finds nothing; in `IgnoreUnlessSpelledInSource` mode the cast is
invisible and every `= 0` initializer matches.

```clang-query
match varDecl(hasInitializer(integerLiteral(equals(0))))
```

**Expected:** 0 matches — every `= 0` is wrapped in an implicit cast.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasInitializer(integerLiteral(equals(0))))
```

**Expected:** 5 matches — `capstone.cpp:44`, `:50`, `:52`, `:138`, `:139`.

**`findAll` → `eachOf(M, forEachDescendant(M))`.** One result for `Shape`
itself and one for the nested `Inner`.

```clang-query
match cxxRecordDecl(hasName("Shape"),
                    eachOf(cxxRecordDecl(isDefinition()).bind("m"),
                           forEachDescendant(cxxRecordDecl(isDefinition()).bind("m"))))
```

**Expected:** 2 matches — both rooted at `Shape` (`capstone.cpp:85`), with `m` bound to `Shape` and then to `Shape::Inner`.

**`functionTypeLoc` → `typeLoc(loc(functionType()))`.** Every written
function type in the file: prototypes, method declarations, definitions.

```clang-query
match typeLoc(loc(functionType()))
```

**Expected:** 46 matches — one per declared function or method signature, from `fail_fast` at `capstone.cpp:17` onwards.

---

## Where to go next

* **clang-tidy sources are matcher collections.** Open
  `clang-tools-extra/clang-tidy/modernize/UseNullptrCheck.cpp` or
  `readability/ContainerSizeEmptyCheck.cpp` in the LLVM tree: the
  `registerMatchers` function is the same expression you wrote here, with
  a `check` callback that emits a diagnostic and a fix-it. Reading them is
  now easy; the extra sophistication you will find (template awareness,
  `isExpensiveToCopy`, fix-it ranges) is exactly the part the DSL leaves out.
* **The C++ `MatchFinder` API** is the same matchers plus a callback and a
  `SourceManager`. The sibling `libtooling-lab`, Part 33, builds that
  callback; every matcher expression from this lab drops in unchanged.
* **Your own scripts.** Keep a `queries/` directory next to any codebase you
  maintain; a `-f` script with `set output diag` is a zero-build lint.

## 12.11 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Build-up by counting | 9 → 7 null casts, 9 → 5 → 3 overriders, 10 → 8 → 4 size comparisons |
| Attribute spelling | `hasAttr("attr::Override")` / `"attr::Final"` are what clang-query 22 accepts |
| Implicit nodes | `unless(isImplicit())` removes compiler-generated overriders |
| Casts in the way | `ignoringImpCasts` / `ignoringParenImpCasts` for promoted literals and `int → bool` conditions |
| `equalsBoundNode` | Compares node identity: bind the `varDecl`/`fieldDecl`, not the `expr` |
| DSL limits | No triviality or size queries; approximate with a user-written copy constructor |
| `has` vs `hasDescendant` | A nested class's virtual destructor must not excuse its parent |
| Case scope | `forEachSwitchCase` sees only this switch's labels; `hasDescendant` leaks into nested switches |
| Macro awareness | `isExpandedFromMacro` and `isExpansionInMainFile` narrow to fixable code |
| Scripts | `-f` files with `#`, `let`, `set output diag\|print\|detailed-ast`, `bind-root`, `print-matcher` |
| Missing names | 14 reference names are absent in clang-query 22; `set traversal`, `eachOf`, `equalsBoundNode` cover the useful ones |

**Quiz.** Write one query that reports only the `SMELL:override` methods that
are *not* destructors and whose class derives directly from `Widget`.

> [!hint]- Hint
> Start from the 12.2 script, add `unless(cxxDestructorDecl())`, and narrow the
> class with `ofClass(isDirectlyDerivedFrom("Widget"))`.

> [!success]- Answer
> `cxxMethodDecl(isOverride(), unless(anyOf(hasAttr("attr::Override"), hasAttr("attr::Final"))), unless(isImplicit()), unless(cxxDestructorDecl()), ofClass(isDirectlyDerivedFrom("Widget")))` — 1 match, `Button::resize` at `capstone.cpp:74`.

---

[← Part 11 — Objective-C, OpenMP, CUDA & Blocks](part_11_objc_openmp_cuda_blocks.md) | [README →](README.md)
