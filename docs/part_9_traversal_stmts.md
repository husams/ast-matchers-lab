# Part 9 — Traversal Matchers II — Statements & Expressions

[← Part 8 — Traversal Matchers I — Tree Navigation & Declarations](part_8_traversal_tree_decls.md) | [Part 10 — Traversal Matchers III — Types, TypeLocs & Templates →](part_10_traversal_types_templates.md)

**Sample:** `manifests/trav_stmts.cpp` · flags: `-std=c++23`

## What You'll Learn
- How to step from a call to its callee, its arguments and its implicit `this` object.
- How the same operand matchers (`hasLHS`, `hasRHS`, …) work across five different operator node kinds.
- How to reach every piece of `if`, `for`, `while`, `do`, `switch` and range-`for` statements.
- How to look *through* the implicit nodes Clang inserts — casts, parentheses, elided copies — with the `ignoring*` family, and when `set traversal IgnoreUnlessSpelledInSource` makes that unnecessary.
- How to traverse `new`, initializer lists, lambda captures and `sizeof`/`alignof`.
- Why `forEach*` matchers need a `.bind()` to report one match per element.

## The Big Picture

Part 8 taught the *generic* traversal matchers (`has`, `hasDescendant`, `hasAncestor`, …) and the ones that step between declarations. This part covers the traversal matchers that step **inside a statement or expression**: from a `CallExpr` to argument 2, from an `IfStmt` to its `else` branch, from a `CXXNewExpr` to its array size.

Each of these matchers names one *role* a child plays in its parent. `has(expr())` says "some child"; `hasCondition(expr())` says "the child that is the condition". Reading a matcher aloud gives the shape of the source:

```
ifStmt(hasCondition(C), hasThen(T), hasElse(E))        if (C) T else E
forStmt(hasLoopInit(I), hasCondition(C),
        hasIncrement(N), hasBody(B))                     for (I; C; N) B
callExpr(callee(F), hasArgument(0, A))                  F(A, ...)
cxxNewExpr(hasPlacementArg(0, P), hasArraySize(S))      new (P) T[S]
```

Two things bite everyone in this part, so meet them now:

1. **Implicit nodes.** In the default `AsIs` traversal, `f(x)` is not `callExpr(hasArgument(0, declRefExpr()))` plus nothing: `x` is wrapped in an `ImplicitCastExpr <LValueToRValue>`. Some role matchers peel that for you (`hasArgument`, `on`), most do not (`hasAnyArgument`, `hasLHS`, `hasCondition`). Section 9.5 gives you the `ignoring*` matchers that peel explicitly, and the one-line `set traversal IgnoreUnlessSpelledInSource` that peels globally.
2. **`forEach*` matchers and `.bind()`.** `forEachSwitchCase`, `forEachLambdaCapture` and `forEachArgumentWithParam` run their inner matcher once per element. clang-query reports one match per *distinct set of bound nodes* — so without a `.bind()` on the element, all the per-element matches collapse into one. Bind the element and the count becomes what you expect.

The sample also contains a defaulted `operator<=>`. Clang synthesises its body (two `if` statements with init-statements and rewritten comparisons), so a few whole-file counts include nodes with no source of their own. Where it matters the examples scope to a function with `hasAncestor(functionDecl(hasName(…)))` or switch traversal mode.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/trav_stmts.cpp -- -std=c++23
```

---

## 9.1 — Calls

A `CallExpr` has a **callee** expression (what is called), **arguments**, and — for member calls — an **implicit object argument** (the thing before the `.` or `->`). The matchers here follow those three edges. `callee` is special: it has two overloads, one that looks at the callee *expression* and one that jumps straight to the callee's *declaration*.

The sample's `calls` function (lines 50–61) calls the overloaded free function `log`, calls through a function pointer, and makes member calls on a `Counter`, a derived `Sub`, a pointer and a temporary.

### `callee(Matcher<Stmt>|Matcher<Decl> InnerMatcher)` — Matcher<CXXFoldExpr>, Matcher<CallExpr>, Matcher<CallExpr>

Two overloads share the name. Given a `Matcher<Decl>`, `callee` matches if the *declaration* being called matches — the everyday form. Given a `Matcher<Stmt>`, it matches the callee *expression* as it sits in the tree: for a plain function call that is an `ImplicitCastExpr <FunctionToPointerDecay>`, for a member call a `MemberExpr`. On a `CXXFoldExpr` the callee is the `UnresolvedLookupExpr` naming the candidate operator functions, and it exists only when unqualified lookup found one at the template's definition.

```clang-query
match callExpr(callee(functionDecl(hasName("log"))))
```

**Expected:** 2 matches — `log(width, "w")` at `trav_stmts.cpp:51` and `log(3)` at line 52. The call through `log_ptr` on line 53 has no declaration as its callee, so it is not matched.

```clang-query
match callExpr(callee(memberExpr()),
               hasAncestor(functionDecl(hasName("calls"))))
```

**Expected:** 6 matches — the member calls on lines 54–59. The `Matcher<Stmt>` overload sees the `MemberExpr` (`c.bump`, `p->bump`, …) that is the callee of each `CXXMemberCallExpr`.

```clang-query
match callExpr(callee(implicitCastExpr(hasSourceExpression(
    declRefExpr(to(varDecl(hasName("log_ptr"))))))))
```

**Expected:** 1 match — `log_ptr(width)` at line 53. The function pointer is read through an `LValueToRValue` cast, so `callee(declRefExpr(...))` alone would find nothing.

```clang-query
match cxxFoldExpr(callee(unresolvedLookupExpr()))
```

**Expected:** 1 match — `(ts * ... * 1)` at line 88. A free `operator*` is declared on line 85, so the fold has a callee; `sum`'s `+` fold (member `operator+` only) and `all`'s `&&` fold have none.

### `hasArgument(unsigned N, Matcher<Expr> InnerMatcher)` — Matcher<CXXConstructExpr>, Matcher<CXXUnresolvedConstructExpr>, Matcher<CallExpr>

Matches the N-th (zero-based) argument of a call, a constructor call, or a dependent `T(args)` construction. The argument is compared **after** stripping parentheses and implicit casts, which is why `declRefExpr()` works directly here.

```clang-query
match callExpr(hasArgument(0, declRefExpr(to(varDecl(hasName("width"))))))
```

**Expected:** 3 matches — `log(width, "w")` (line 51), `log_ptr(width)` (line 53) and `c.bump(width)` (line 55).

```clang-query
match cxxConstructExpr(hasArgument(1, integerLiteral(equals(4))))
```

**Expected:** 1 match — `Widget box(3, 4)` at line 60.

```clang-query
match cxxUnresolvedConstructExpr(hasArgument(0, declRefExpr()))
```

**Expected:** 1 match — `T(t)` at line 74, inside the template `inspect` where `T` is still unknown.

### `hasAnyArgument(Matcher<Expr> InnerMatcher)` — Matcher<CXXConstructExpr>, Matcher<CXXUnresolvedConstructExpr>, Matcher<CallExpr>

Matches if *any* argument matches. Unlike `hasArgument`, this one does **not** strip implicit casts, so you usually pair it with `ignoringImpCasts`.

```clang-query
match callExpr(hasAnyArgument(declRefExpr(to(varDecl(hasName("width"))))))
```

**Expected:** 0 matches — every use of `width` sits under an `LValueToRValue` cast that `hasAnyArgument` does not peel.

```clang-query
match callExpr(hasAnyArgument(ignoringImpCasts(
    declRefExpr(to(varDecl(hasName("width")))))))
```

**Expected:** 3 matches — the same three calls as the `hasArgument` example (lines 51, 53, 55).

```clang-query
match cxxConstructExpr(hasAnyArgument(integerLiteral()))
```

**Expected:** 1 match — `Widget box(3, 4)` at line 60.

```clang-query
match cxxUnresolvedConstructExpr(hasAnyArgument(declRefExpr()))
```

**Expected:** 1 match — `T(t)` at line 74.

### `forEachArgumentWithParam(Matcher<Expr> ArgMatcher, Matcher<ParmVarDecl> ParamMatcher)` — Matcher<CXXConstructExpr>, Matcher<CallExpr>

Walks the arguments of a call or constructor call *together with* the parameter each one lands in. For every (argument, parameter) pair where both matchers match, the call is reported once — but only as a separate match when you bind something on the pair; unbound duplicates collapse (see Big Picture). Calls through function pointers have no `ParmVarDecl`, so they never match here.

```clang-query
match callExpr(forEachArgumentWithParam(
    declRefExpr(to(varDecl(hasName("width")))).bind("arg"),
    parmVarDecl().bind("param")))
```

**Expected:** 2 matches — `log(width, "w")` at line 51 (parameter `level`) and `c.bump(width)` at line 55 (parameter `by`). `log_ptr(width)` is skipped: a pointer call has no parameter declaration.

```clang-query
match cxxConstructExpr(forEachArgumentWithParam(
    integerLiteral().bind("arg"), parmVarDecl().bind("param")))
```

**Expected:** 2 matches — both `Widget box(3, 4)` at line 60, once for `3`→`w` and once for `4`→`h`.

```clang-query
match cxxConstructExpr(forEachArgumentWithParam(integerLiteral(), parmVarDecl()))
```

**Expected:** 1 match — the same constructor call, but without `.bind()` the two per-argument results carry identical bound nodes and are reported once.

### `forEachArgumentWithParamType(Matcher<Expr> ArgMatcher, Matcher<QualType> ParamMatcher)` — Matcher<CXXConstructExpr>, Matcher<CallExpr>

The same idea, but the second matcher sees the parameter's **type** instead of its declaration. Because a function pointer's type still lists parameter types, calls through pointers are covered too.

```clang-query
match callExpr(forEachArgumentWithParamType(
    declRefExpr(to(varDecl(hasName("width")))).bind("arg"),
    qualType(isInteger()).bind("type")))
```

**Expected:** 3 matches — lines 51, 53 and 55. Compare with `forEachArgumentWithParam`, which missed `log_ptr(width)` on line 53.

```clang-query
match cxxConstructExpr(forEachArgumentWithParamType(
    integerLiteral().bind("arg"), qualType(isInteger()).bind("type")))
```

**Expected:** 2 matches — `Widget box(3, 4)` at line 60, once per argument.

### `on(Matcher<Expr> InnerMatcher)` — Matcher<CXXMemberCallExpr>

Matches the implicit object argument of a member call — the `c` in `c.bump()` — **after** stripping parentheses and implicit casts (including the derived-to-base cast Clang inserts for `s.bump()` and the temporary materialisation in `(make()).bump()`).

```clang-query
match cxxMemberCallExpr(on(hasType(cxxRecordDecl(hasName("Counter")))))
```

**Expected:** 3 matches — `c.bump()` (line 54), `c.bump(width)` (line 55) and `(make()).bump()` (line 59). `s.bump()` is *not* here: after peeling, the object is `s` of type `Sub`. `p->bump()` is not here either: `p` has pointer type.

```clang-query
match cxxMemberCallExpr(on(hasType(cxxRecordDecl(hasName("Sub")))))
```

**Expected:** 2 matches — `s.bump()` (line 56) and `s.extra()` (line 57).

```clang-query
match cxxMemberCallExpr(on(callExpr()))
```

**Expected:** 1 match — `(make()).bump()` at line 59; the parentheses and the temporary are ignored.

### `onImplicitObjectArgument(Matcher<Expr> InnerMatcher)` — Matcher<CXXMemberCallExpr>

Like `on`, but matches the implicit object argument **exactly as it is in the tree**, without stripping anything.

```clang-query
match cxxMemberCallExpr(onImplicitObjectArgument(
    hasType(cxxRecordDecl(hasName("Counter")))))
```

**Expected:** 4 matches — lines 54, 55, 56 and 59. `s.bump()` now counts: its object argument is an `ImplicitCastExpr <DerivedToBase>` whose type is `Counter`.

```clang-query
match cxxMemberCallExpr(onImplicitObjectArgument(materializeTemporaryExpr()))
```

**Expected:** 1 match — `(make()).bump()` at line 59. The raw object argument is a `MaterializeTemporaryExpr`, not a `ParenExpr` or a `CallExpr`; `on(callExpr())` only worked because it peeled that wrapper.

### `thisPointerType(Matcher<QualType>|Matcher<Decl> InnerMatcher)` — Matcher<CXXMemberCallExpr>, Matcher<CXXMemberCallExpr>

Matches if the type of the implicit object argument matches, *or* is a pointer to a type that matches — so `.` calls and `->` calls are treated alike. The `Matcher<Decl>` overload lets you name the class directly; the `Matcher<QualType>` overload gives you the type.

```clang-query
match cxxMemberCallExpr(thisPointerType(cxxRecordDecl(hasName("Counter"))))
```

**Expected:** 5 matches — lines 54, 55, 56, 58 and 59. `p->bump()` (line 58) joins because the pointer is looked through; `s.bump()` joins because the derived-to-base cast is kept (this is `onImplicitObjectArgument` underneath).

```clang-query
match cxxMemberCallExpr(thisPointerType(hasDeclaration(cxxRecordDecl(hasName("Counter")))))
```

**Expected:** 5 matches — the same five calls, written through the `QualType` overload.

```clang-query
match cxxMemberCallExpr(thisPointerType(cxxRecordDecl(hasName("Sub"))))
```

**Expected:** 1 match — `s.extra()` at line 57, the only call whose object argument still has type `Sub`.

### `hasAnyDeclaration(Matcher<Decl> InnerMatcher)` — Matcher<OverloadExpr>

An `OverloadExpr` (an `UnresolvedLookupExpr` or `UnresolvedMemberExpr`) is a name in a template that resolved to a *set* of candidates and cannot be narrowed until instantiation. `hasAnyDeclaration` matches if any candidate in the set matches.

```clang-query
match unresolvedLookupExpr(hasAnyDeclaration(functionTemplateDecl(hasName("over"))))
```

**Expected:** 1 match — `over` in `over(t)` at line 70, whose set holds both `over` templates. `other(t)` on line 71 is not matched.

```clang-query
match unresolvedMemberExpr(hasAnyDeclaration(cxxMethodDecl(hasName("push"))))
```

**Expected:** 1 match — `s.push` in `s.push(t)` at line 72; `push` is overloaded and `t` is dependent, so the member stays unresolved.

---

## 9.2 — Operators

Clang represents "an operator with operands" with five different node kinds, and the operand matchers are overloaded to work on all of them:

```
BinaryOperator             i * 2            built-in binary operator
UnaryOperator              -i, !both        built-in unary operator
CXXOperatorCallExpr        a + b, -a        overloaded operator (a call in disguise)
CXXRewrittenBinaryOperator a != b, a < b    C++20 rewrite via == / <=>
CXXFoldExpr                (0 + ... + ts)   fold over a parameter pack
ArraySubscriptExpr         grid[i]          base [ index ]
```

The operands of an *overloaded* operator are call arguments, so they carry the implicit nodes of a call: `a` becomes `ImplicitCastExpr <NoOp> const Vec`, and by-value `b` becomes a copy `CXXConstructExpr`. The examples show both the `AsIs` form with `ignoringImpCasts` and the `IgnoreUnlessSpelledInSource` form where the operand is just `declRefExpr()`.

### `hasLHS(Matcher<Expr> InnerMatcher)` — Matcher<ArraySubscriptExpr>, Matcher<BinaryOperator>, Matcher<CXXFoldExpr>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

Matches the left operand: the left side of a binary operator, the base of a subscript, the left operand of a fold (before the `...`), or the first argument of an overloaded binary operator.

```clang-query
match binaryOperator(hasLHS(ignoringImpCasts(declRefExpr(to(varDecl(hasName("i")))))))
```

**Expected:** 4 matches — `i * 2` (line 94), `i > 0` and `i < 8` (line 95), and `i < n` in the `for` header at line 117.

```clang-query
match cxxOperatorCallExpr(hasLHS(ignoringImpCasts(declRefExpr(to(varDecl(hasName("a")))))))
```

**Expected:** 3 matches — `a + b` at line 96, plus the `a == b` and `a <=> b` calls that live *inside* the rewritten operators on lines 99 and 100.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match cxxOperatorCallExpr(hasLHS(declRefExpr(to(varDecl(hasName("a"))))))
```

**Expected:** 2 matches — `a + b` (line 96) and `a * 3` (line 98). In this mode the implicit casts vanish, and so do the inner calls synthesised for the rewritten operators.

```clang-query
match cxxRewrittenBinaryOperator(hasLHS(ignoringImpCasts(declRefExpr(to(varDecl(hasName("a")))))))
```

**Expected:** 2 matches — `a != b` (line 99, rewritten from `==`) and `a < b` (line 100, rewritten from `<=>`).

```clang-query
match cxxFoldExpr(hasLHS(integerLiteral(equals(0))))
```

**Expected:** 1 match — `(0 + ... + ts)` at line 87; the LHS of a fold is whatever is written before the `...`.

```clang-query
match arraySubscriptExpr(hasLHS(implicitCastExpr(hasSourceExpression(declRefExpr()))))
```

**Expected:** 1 match — `grid[i]` at line 101, where the LHS is the array-to-pointer decay of `grid`.

### `hasRHS(Matcher<Expr> InnerMatcher)` — Matcher<ArraySubscriptExpr>, Matcher<BinaryOperator>, Matcher<CXXFoldExpr>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

The mirror image: the right operand, the subscript index, the operand after `...`, or the second argument of an overloaded operator.

```clang-query
match binaryOperator(hasRHS(integerLiteral(equals(1))))
```

**Expected:** 4 matches — `… + 1` (line 94), `n = 1` (line 114), `n -= 1` (line 117) and `tmp + 1` (line 133).

```clang-query
match cxxOperatorCallExpr(hasRHS(integerLiteral(equals(3))))
```

**Expected:** 1 match — `a * 3` at line 98.

```clang-query
match cxxRewrittenBinaryOperator(hasRHS(ignoringImpCasts(declRefExpr(to(varDecl(hasName("b")))))))
```

**Expected:** 2 matches — lines 99 and 100.

```clang-query
match cxxFoldExpr(hasRHS(integerLiteral(equals(1))))
```

**Expected:** 1 match — `(ts * ... * 1)` at line 88.

```clang-query
match arraySubscriptExpr(hasRHS(implicitCastExpr(hasSourceExpression(declRefExpr()))))
```

**Expected:** 1 match — `grid[i]` at line 101.

### `hasEitherOperand(Matcher<Expr> InnerMatcher)` — Matcher<BinaryOperator>, Matcher<CXXFoldExpr>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

Matches if the left *or* the right operand matches. Handy when you do not care which side a literal is on.

```clang-query
match binaryOperator(hasEitherOperand(integerLiteral(equals(8))))
```

**Expected:** 1 match — `i < 8` at line 95.

```clang-query
match cxxOperatorCallExpr(hasEitherOperand(integerLiteral(equals(3))))
```

**Expected:** 1 match — `a * 3` at line 98.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match cxxRewrittenBinaryOperator(hasEitherOperand(declRefExpr(to(varDecl(hasName("b"))))))
```

**Expected:** 2 matches — lines 99 and 100.

```clang-query
match cxxFoldExpr(hasEitherOperand(integerLiteral(equals(1))))
```

**Expected:** 1 match — `(ts * ... * 1)` at line 88.

### `hasOperands(Matcher<Expr> Matcher1, Matcher<Expr> Matcher2)` — Matcher<BinaryOperator>, Matcher<CXXFoldExpr>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

Matches if the two matchers match the two operands in *either* order — `hasOperands(A, B)` is `hasLHS(A), hasRHS(B)` or `hasLHS(B), hasRHS(A)`.

```clang-query
match binaryOperator(hasOperands(integerLiteral(equals(2)), ignoringImpCasts(declRefExpr())))
```

**Expected:** 3 matches — `i * 2` (line 94), `n = 2` (line 114) and `n * 2` (line 133). The literal is on the right in all three, and the matcher did not need to know that.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match cxxOperatorCallExpr(hasOperands(declRefExpr(to(varDecl(hasName("a")))),
                                      integerLiteral(equals(3))))
```

**Expected:** 1 match — `a * 3` at line 98.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match cxxRewrittenBinaryOperator(hasOperands(declRefExpr(to(varDecl(hasName("b")))),
                                             declRefExpr(to(varDecl(hasName("a"))))))
```

**Expected:** 2 matches — lines 99 and 100, even though `b` is written second in both.

```clang-query
match cxxFoldExpr(hasOperands(integerLiteral(), declRefExpr()))
```

**Expected:** 2 matches — `(0 + ... + ts)` (line 87) and `(ts * ... * 1)` (line 88). The unary fold `(... && ts)` on line 89 has only one operand.

### `hasUnaryOperand(Matcher<Expr> InnerMatcher)` — Matcher<CXXOperatorCallExpr>, Matcher<UnaryOperator>

Matches the single operand of a built-in unary operator, or the single argument of an overloaded unary operator such as `-a`.

```clang-query
match unaryOperator(hasUnaryOperand(ignoringImpCasts(declRefExpr(to(varDecl(hasName("i")))))))
```

**Expected:** 2 matches — `-i` at line 102 and `++i` in the `for` header at line 117.

```clang-query
match cxxOperatorCallExpr(hasUnaryOperand(ignoringImpCasts(declRefExpr(to(varDecl(hasName("a")))))))
```

**Expected:** 1 match — `-a` at line 97, the call to `Vec::operator-`.

### `hasBase(Matcher<Expr> InnerMatcher)` — Matcher<ArraySubscriptExpr>

Matches the array (or pointer) being indexed. In `AsIs` mode an array name decays first, so the base is an `ImplicitCastExpr <ArrayToPointerDecay>`.

```clang-query
match arraySubscriptExpr(hasBase(implicitCastExpr(hasSourceExpression(
    declRefExpr(to(varDecl(hasName("grid"))))))))
```

**Expected:** 1 match — `grid[i]` at line 101.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match arraySubscriptExpr(hasBase(declRefExpr(to(varDecl(hasName("grid"))))))
```

**Expected:** 1 match — the same subscript, with the decay cast hidden.

### `hasIndex(Matcher<Expr> InnerMatcher)` — Matcher<ArraySubscriptExpr>

Matches the index expression inside the brackets.

```clang-query
match arraySubscriptExpr(hasIndex(ignoringImpCasts(declRefExpr(to(varDecl(hasName("i")))))))
```

**Expected:** 1 match — `grid[i]` at line 101.

### `hasFoldInit(Matcher<Expr> InnerMacher)` — Matcher<CXXFoldExpr>

In a *binary* fold, matches the operand that does **not** contain the pack — the initial value (`0` in `(0 + ... + ts)`, `1` in `(ts * ... * 1)`). Unary folds have no init and never match.

```clang-query
match cxxFoldExpr(hasFoldInit(integerLiteral()))
```

**Expected:** 2 matches — the folds on lines 87 and 88. `(... && ts)` on line 89 is a unary fold.

```clang-query
match cxxFoldExpr(hasFoldInit(integerLiteral(equals(1))))
```

**Expected:** 1 match — `(ts * ... * 1)` at line 88, regardless of which side the init is on.

### `hasPattern(Matcher<Expr> InnerMacher)` — Matcher<CXXFoldExpr>

Matches the operand that **contains** the pack — the `ts` in every fold. Together, `hasFoldInit` and `hasPattern` are the side-independent way to read a fold; `hasLHS`/`hasRHS` depend on where the `...` was written.

```clang-query
match cxxFoldExpr(hasPattern(declRefExpr()))
```

**Expected:** 3 matches — all three folds on lines 87, 88 and 89.

---

## 9.3 — Control flow

The `control` function (lines 113–136) has one of everything: `if`/`else`, `if` with an init-statement, `if` declaring its condition variable, three kinds of `for`, `while`, `do`, three `switch` forms, the ternary operator, the GNU `?:` operator, a statement-expression and a nested block. Each matcher below names one slot of one of these statements.

```
if (INIT; COND) THEN else ELSE        hasInitStatement / hasCondition / hasThen / hasElse
if (T v = COND) …                     hasConditionVariableStatement
for (INIT; COND; INC) BODY            hasLoopInit / hasCondition / hasIncrement / hasBody
for (INIT; VAR : RANGE) BODY          hasInitStatement / hasLoopVariable / hasRangeInit / hasBody
switch (INIT; COND) { case C: … }     hasInitStatement / hasCondition / forEachSwitchCase / hasCaseConstant
COND ? TRUE : FALSE                   hasCondition / hasTrueExpression / hasFalseExpression
```

### `hasCondition(Matcher<Expr> InnerMatcher)` — Matcher<AbstractConditionalOperator>, Matcher<DoStmt>, Matcher<ForStmt>, Matcher<IfStmt>, Matcher<SwitchStmt>, Matcher<WhileStmt>

Matches the condition expression of an `if`, `for`, `while`, `do`, `switch`, or of the `?:` operators (`conditionalOperator` and `binaryConditionalOperator` both derive from `AbstractConditionalOperator`). Nothing is peeled: a pointer used as a condition is an `ImplicitCastExpr <PointerToBoolean>`.

```clang-query
match ifStmt(hasCondition(binaryOperator(hasOperatorName(">"))))
```

**Expected:** 2 matches — `if (n > 0)` at line 114 and `if (int k = probe(); k > 3)` at line 115.

```clang-query
match forStmt(hasCondition(binaryOperator(hasOperatorName("<"))))
```

**Expected:** 1 match — `for (int i = 0; i < n; ++i)` at line 117.

```clang-query
match whileStmt(hasCondition(binaryOperator(hasOperatorName(">"))))
```

**Expected:** 1 match — `while (n > 100)` at line 119.

```clang-query
match doStmt(hasCondition(binaryOperator(hasOperatorName("<"))))
```

**Expected:** 1 match — `do { n++; } while (n < 10)` at line 121.

```clang-query
match switchStmt(hasCondition(ignoringImpCasts(declRefExpr(to(varDecl(hasName("n")))))))
```

**Expected:** 1 match — `switch (n)` at line 122.

```clang-query
match conditionalOperator(hasCondition(ignoringImpCasts(declRefExpr(to(parmVarDecl(hasName("n")))))))
```

**Expected:** 1 match — `n ? n : 1` at line 131.

```clang-query
match binaryConditionalOperator(hasCondition(ignoringImpCasts(opaqueValueExpr())))
```

**Expected:** 1 match — `n ?: 7` at line 132. In the GNU form the condition is evaluated once and reused, which Clang models with an `OpaqueValueExpr` (see `hasSourceExpression` in 9.6).

```clang-query
match ifStmt(hasCondition(ignoringImpCasts(declRefExpr(to(varDecl(hasName("nd")))))))
```

**Expected:** 1 match — `if (Node* nd = head())` at line 116: the condition of a declaration-condition is a read of the freshly declared variable, converted to `bool`.

### `hasTrueExpression(Matcher<Expr> InnerMatcher)` — Matcher<AbstractConditionalOperator>

Matches the branch taken when the condition is true. For the GNU `a ?: b`, the true branch *is* the condition, seen through the same `OpaqueValueExpr`.

```clang-query
match conditionalOperator(hasTrueExpression(ignoringImpCasts(declRefExpr(to(parmVarDecl(hasName("n")))))))
```

**Expected:** 1 match — `n ? n : 1` at line 131.

```clang-query
match binaryConditionalOperator(hasTrueExpression(opaqueValueExpr()))
```

**Expected:** 1 match — `n ?: 7` at line 132.

### `hasFalseExpression(Matcher<Expr> InnerMatcher)` — Matcher<AbstractConditionalOperator>

Matches the branch taken when the condition is false — the part after the `:` in both forms.

```clang-query
match conditionalOperator(hasFalseExpression(integerLiteral(equals(1))))
```

**Expected:** 1 match — `n ? n : 1` at line 131.

```clang-query
match binaryConditionalOperator(hasFalseExpression(integerLiteral(equals(7))))
```

**Expected:** 1 match — `n ?: 7` at line 132.

### `hasThen(Matcher<Stmt> InnerMatcher)` — Matcher<IfStmt>

Matches the statement executed when the `if` condition holds. It may be a compound statement or a single statement.

```clang-query
match ifStmt(hasThen(compoundStmt(has(binaryOperator(hasRHS(integerLiteral(equals(1))))))))
```

**Expected:** 1 match — `if (n > 0) { n = 1; } …` at line 114.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match ifStmt(hasThen(returnStmt()))
```

**Expected:** 1 match — `if (positive(v)) return v;` at line 178. (In `AsIs` mode the synthesised body of the defaulted `operator<=>` contributes two more.)

### `hasElse(Matcher<Stmt> InnerMatcher)` — Matcher<IfStmt>

Matches the `else` branch. An `if` without `else` never matches, whatever the inner matcher.

```clang-query
match ifStmt(hasElse(compoundStmt(has(binaryOperator(hasRHS(integerLiteral(equals(2))))))))
```

**Expected:** 1 match — the `if`/`else` at line 114.

```clang-query
match ifStmt(hasElse(stmt()))
```

**Expected:** 1 match — line 114 is the only `if` in the sample with an `else`.

### `hasInitStatement(Matcher<Stmt> InnerMatcher)` — Matcher<CXXForRangeStmt>, Matcher<IfStmt>, Matcher<SwitchStmt>

Matches the C++17 init-statement — the part before the first `;` in `if (init; cond)`, `switch (init; cond)` and the C++20 `for (init; var : range)`.

```clang-query
match ifStmt(hasInitStatement(declStmt()),
             hasAncestor(functionDecl(hasName("control"))))
```

**Expected:** 1 match — `if (int k = probe(); k > 3)` at line 115. The `hasAncestor` keeps out the two implicit `if (auto cmp = …; cmp != 0)` statements Clang writes for the defaulted `<=>`.

```clang-query
match switchStmt(hasInitStatement(declStmt(hasSingleDecl(varDecl(hasName("m"))))))
```

**Expected:** 1 match — `switch (int m = probe(); m)` at line 127.

```clang-query
match cxxForRangeStmt(hasInitStatement(declStmt(hasSingleDecl(varDecl(hasName("r"))))))
```

**Expected:** 1 match — `for (auto r = values(); int v : r)` at line 130.

### `hasConditionVariableStatement(Matcher<DeclStmt> InnerMatcher)` — Matcher<ForStmt>, Matcher<IfStmt>, Matcher<SwitchStmt>, Matcher<WhileStmt>

Matches the `DeclStmt` of a variable declared *in the condition itself* — `if (Node* nd = head())`. This is different from an init-statement: there is no `;`, and the variable's value is the condition.

```clang-query
match ifStmt(hasConditionVariableStatement(declStmt()))
```

**Expected:** 1 match — `if (Node* nd = head())` at line 116.

```clang-query
match forStmt(hasConditionVariableStatement(declStmt(hasSingleDecl(varDecl(hasName("nd"))))))
```

**Expected:** 1 match — `for (; Node* nd = head();)` at line 118.

```clang-query
match whileStmt(hasConditionVariableStatement(declStmt()))
```

**Expected:** 1 match — `while (Node* nd = head())` at line 120.

```clang-query
match switchStmt(hasConditionVariableStatement(declStmt(hasSingleDecl(varDecl(hasName("m"))))))
```

**Expected:** 1 match — `switch (int m = probe())` at line 128. Line 127 does not match: its `m` is an init-statement, and its condition is the plain expression `m`.

### `hasLoopInit(Matcher<Stmt> InnerMatcher)` — Matcher<ForStmt>

Matches the first clause of a classic `for` — a `DeclStmt` or an expression.

```clang-query
match forStmt(hasLoopInit(declStmt(hasSingleDecl(varDecl(hasName("i"))))))
```

**Expected:** 1 match — `for (int i = 0; …)` at line 117. The `for (; …;)` at line 118 has an empty init clause.

### `hasIncrement(Matcher<Stmt> InnerMatcher)` — Matcher<ForStmt>

Matches the third clause of a classic `for`.

```clang-query
match forStmt(hasIncrement(unaryOperator(hasOperatorName("++"))))
```

**Expected:** 1 match — `++i` in the `for` at line 117.

### `hasBody(Matcher<Stmt> InnerMatcher)` — Matcher<CXXForRangeStmt>, Matcher<CoroutineBodyStmt>, Matcher<DoStmt>, Matcher<ForStmt>, Matcher<FunctionDecl>, Matcher<WhileStmt>

Matches the body of a loop, a function *definition*, or a coroutine. For functions, only the declaration that carries the body matches. A coroutine's `FunctionDecl` body is a `CoroutineBodyStmt` wrapping the written `CompoundStmt`, so it takes two `hasBody` steps to reach the braces.

```clang-query
match forStmt(hasBody(compoundStmt(has(binaryOperator(hasOperatorName("-="))))))
```

**Expected:** 1 match — the `for` at line 117.

```clang-query
match cxxForRangeStmt(hasBody(compoundStmt(has(binaryOperator(hasOperatorName("+="))))))
```

**Expected:** 2 matches — the range-`for` loops at lines 129 and 130.

```clang-query
match whileStmt(hasBody(compoundStmt(has(unaryOperator(hasOperatorName("--"))))))
```

**Expected:** 1 match — `while (n > 100) { --n; }` at line 119.

```clang-query
match doStmt(hasBody(compoundStmt(has(unaryOperator(hasOperatorName("++"))))))
```

**Expected:** 1 match — `do { n++; } …` at line 121.

```clang-query
match functionDecl(hasName("calls"), hasBody(compoundStmt()))
```

**Expected:** 1 match — the definition of `calls` at line 50.

```clang-query
match functionDecl(hasName("log"), hasBody(stmt()))
```

**Expected:** 0 matches — both `log` declarations (lines 31–32) are prototypes without a body.

```clang-query
match functionDecl(hasBody(coroutineBodyStmt(hasBody(compoundStmt(has(coreturnStmt()))))))
```

**Expected:** 1 match — `Task ticker() { co_return; }` at line 152. The outer `hasBody` is the `FunctionDecl` overload, the inner one the `CoroutineBodyStmt` overload.

### `hasLoopVariable(Matcher<VarDecl> InnerMatcher)` — Matcher<CXXForRangeStmt>

Matches the variable declared before the `:` of a range-`for`.

```clang-query
match cxxForRangeStmt(hasLoopVariable(varDecl(hasName("v"))))
```

**Expected:** 2 matches — lines 129 and 130.

### `hasRangeInit(Matcher<Expr> InnerMatcher)` — Matcher<CXXForRangeStmt>

Matches the expression after the `:`. A temporary range is materialised for the hidden `__range` variable, so a call result is wrapped in implicit nodes — peel them with `ignoringImplicit`.

```clang-query
match cxxForRangeStmt(hasRangeInit(ignoringImplicit(callExpr())))
```

**Expected:** 1 match — `for (int v : values())` at line 129.

```clang-query
match cxxForRangeStmt(hasRangeInit(declRefExpr(to(varDecl(hasName("r"))))))
```

**Expected:** 1 match — `for (auto r = values(); int v : r)` at line 130.

### `forEachSwitchCase(Matcher<SwitchCase> InnerMatcher)` — Matcher<SwitchStmt>

Runs the inner matcher on every `case`/`default` label that belongs to the switch (not to a nested switch). Bind the label to get one match per label.

```clang-query
match switchStmt(forEachSwitchCase(switchCase().bind("c")))
```

**Expected:** 5 matches — the switch at line 122 three times (`case 1`, `case 2 ... 4`, `default`), the switch at line 127 once (`case 1`) and the switch at line 128 once (`default`).

```clang-query
match switchStmt(forEachSwitchCase(switchCase()))
```

**Expected:** 3 matches — the same three switches, once each: with nothing bound on the label the per-label results are identical and collapse.

### `hasCaseConstant(Matcher<Expr> InnerMatcher)` — Matcher<CaseStmt>

Matches the constant of a `case` label — unless the label uses the GNU range extension `case 2 ... 4:`, which never matches. In C++ the constant is wrapped in a `ConstantExpr` node, so use `ignoringImplicit` (or switch traversal mode) to reach the literal.

```clang-query
match caseStmt(hasCaseConstant(ignoringImplicit(integerLiteral(equals(1)))))
```

**Expected:** 2 matches — `case 1:` at line 123 and `case 1:` at line 127.

```clang-query
match caseStmt(hasCaseConstant(integerLiteral()))
```

**Expected:** 0 matches — the `ConstantExpr` wrapper sits between the label and the literal in `AsIs` mode.

### `hasReturnValue(Matcher<Expr> InnerMatcher)` — Matcher<ReturnStmt>

Matches the expression returned. A bare `return;` never matches.

```clang-query
match returnStmt(hasReturnValue(cxxFoldExpr()))
```

**Expected:** 3 matches — the `return` statements of `sum`, `product` and `all` on lines 87–89.

```clang-query
match returnStmt(hasReturnValue(integerLiteral(equals(0))))
```

**Expected:** 1 match — `return 0;` at line 179.

### `hasAnySubstatement(Matcher<Stmt> InnerMatcher)` — Matcher<CompoundStmt>, Matcher<StmtExpr>

Matches a `{ … }` block if at least one of its *direct* statements matches. The `StmtExpr` overload lets you look into a GNU statement-expression `({ … })` the same way.

```clang-query
match compoundStmt(hasAnySubstatement(compoundStmt()))
```

**Expected:** 2 matches — the body of `control` (line 113), because it directly contains the block on line 134, and that block itself, because it directly contains `{}`.

```clang-query
match stmtExpr(hasAnySubstatement(declStmt()))
```

**Expected:** 1 match — `({ int tmp = n * 2; tmp + 1; })` at line 133.

---

## 9.4 — Declarations inside statements

These matchers connect expressions and statements back to declarations: a `DeclStmt` to the variables it declares, a `DeclRefExpr` to what it names, a `MemberExpr` to its member and its object, and any statement to the function it lives in.

### `hasSingleDecl(Matcher<Decl> InnerMatcher)` — Matcher<DeclStmt>

Matches a `DeclStmt` that declares exactly one thing, if that declaration matches. `int a, b = 0;` declares two, so it never matches.

```clang-query
match declStmt(hasSingleDecl(varDecl(hasName("p"))))
```

**Expected:** 1 match — `Pair p{1, 2};` at line 170.

```clang-query
match declStmt(hasSingleDecl(anything()),
               hasAncestor(functionDecl(hasName("decls"))))
```

**Expected:** 2 matches — `int c;` (line 168) and `Pair p{1, 2};` (line 170). Lines 167 and 169 declare two variables each.

### `containsDeclaration(unsigned N, Matcher<Decl> InnerMatcher)` — Matcher<DeclStmt>

Matches the N-th declaration of a `DeclStmt`. This only works for *local* declarations: at file scope Clang splits `int a, b;` into separate declarations with no `DeclStmt` at all.

```clang-query
match declStmt(containsDeclaration(1, varDecl()))
```

**Expected:** 3 matches — `int a, b = 0;` (line 167), `int d = 2, e;` (line 169) and `int x = 1, y = 2;` (line 226): the statements that have a second declaration at all.

```clang-query
match declStmt(containsDeclaration(0, varDecl(hasInitializer(anything()))),
               hasAncestor(functionDecl(hasName("decls"))))
```

**Expected:** 2 matches — `int d = 2, e;` (line 169) and `Pair p{1, 2};` (line 170). In `int a, b = 0;` the *first* declaration has no initializer.

### `to(Matcher<Decl> InnerMatcher)` — Matcher<DeclRefExpr>

Matches a reference to a name if the declaration it refers to matches. This is the everyday way to say "a use of variable `x`" or "a mention of function `f`".

```clang-query
match declRefExpr(to(varDecl(hasName("width"))))
```

**Expected:** 3 matches — the uses of `width` on lines 51, 53 and 55.

```clang-query
match declRefExpr(to(functionDecl(hasName("head"))))
```

**Expected:** 3 matches — the `head` in each `head()` call on lines 116, 118 and 120.

### `member(Matcher<ValueDecl> InnerMatcher)` — Matcher<MemberExpr>

Matches a member access `obj.m` / `p->m` / implicit `this->m` if the member declaration matches.

```clang-query
match memberExpr(member(hasName("first")))
```

**Expected:** 2 matches — `pr.first` at line 162 and `p.first` at line 171.

```clang-query
match memberExpr(member(fieldDecl(hasName("second"))))
```

**Expected:** 1 match — `p.second` at line 172.

### `hasObjectExpression(Matcher<Expr> InnerMatcher)` — Matcher<CXXDependentScopeMemberExpr>, Matcher<MemberExpr>, Matcher<UnresolvedMemberExpr>

Matches the object part of a member access — the `h` in `h.m`. Implicit `this` counts: inside a method, a bare `m` is `this->m`, and its object expression is a `CXXThisExpr` of pointer type. The two dependent overloads reach the object of a member access in a template that cannot be resolved yet.

```clang-query
match memberExpr(hasObjectExpression(hasType(cxxRecordDecl(hasName("Holder")))))
```

**Expected:** 1 match — `h.m` at line 161.

```clang-query
match memberExpr(hasObjectExpression(hasType(pointsTo(cxxRecordDecl(hasName("Holder"))))))
```

**Expected:** 2 matches — the implicit `this->m` and `this->pr` in `return a + m + pr.first;` at line 162.

```clang-query
match memberExpr(hasObjectExpression(ignoringImpCasts(declRefExpr(to(varDecl(hasName("nd")))))))
```

**Expected:** 3 matches — `nd->val` on lines 116, 118 and 120.

```clang-query
match cxxDependentScopeMemberExpr(hasObjectExpression(declRefExpr(to(parmVarDecl(hasName("t"))))))
```

**Expected:** 1 match — `t.size` in `t.size()` at line 73, where `t` has the dependent type `T`.

```clang-query
match unresolvedMemberExpr(hasObjectExpression(declRefExpr(to(parmVarDecl(hasName("s"))))))
```

**Expected:** 1 match — `s.push` in `s.push(t)` at line 72: `s` is a concrete `Stack&`, but `push` is overloaded and the argument is dependent.

### `forFunction(Matcher<FunctionDecl> InnerMatcher)` — Matcher<Stmt>

Matches a statement if the function whose body contains it matches. A lambda body belongs to the lambda's `operator()`, *not* to the enclosing function — that is exactly what makes this different from `hasAncestor`. Deprecated in favour of `forCallable`, which also understands blocks and Objective-C methods.

```clang-query
match returnStmt(forFunction(functionDecl(hasName("pick"))))
```

**Expected:** 2 matches — `return v;` (line 178) and `return 0;` (line 179). The `return q > 0;` inside the lambda on line 177 belongs to the lambda.

```clang-query
match returnStmt(forFunction(hasName("operator()")))
```

**Expected:** 4 matches — the `return` inside each lambda body on lines 177, 228, 229 and 230.

### `forCallable(Matcher<Decl> InnerMatcher)` — Matcher<Stmt>

The modern form of `forFunction`: matches a statement by the function, method, lambda call operator, block or Objective-C method that directly owns it.

```clang-query
match returnStmt(forCallable(cxxMethodDecl(hasName("operator()"))))
```

**Expected:** 4 matches — the same four lambda `return` statements (lines 177, 228, 229, 230).

```clang-query
match declStmt(forCallable(functionDecl(hasName("pick"))))
```

**Expected:** 1 match — `auto positive = …;` at line 177, the only declaration statement directly inside `pick`.

---

## 9.5 — The `ignoring*` family

The `ignoring` function (lines 186–199) initialises twelve variables, each with a different kind of wrapper between the `=` and the interesting node:

```
line  source                              top node in AsIs mode
188   int a = 0;                          IntegerLiteral
189   char b = (0);                       ImplicitCastExpr > ParenExpr > IntegerLiteral
190   const int c = a;                    ImplicitCastExpr > DeclRefExpr
191   int* d = (arr);                     ImplicitCastExpr > ParenExpr > DeclRefExpr
192   long e = ((long)0l);                ParenExpr > CStyleCastExpr > IntegerLiteral
193   void* f = reinterpret_cast<…>(0);   ImplicitCastExpr > CXXReinterpretCastExpr > IntegerLiteral
194   char g = char(0);                   CXXFunctionalCastExpr > IntegerLiteral
195   Cell h = Cell();                    CXXTemporaryObjectExpr   (a CXXConstructExpr)
196   Cell i;                             CXXConstructExpr
197   Cell j = i;                         CXXConstructExpr (copy) > ImplicitCastExpr > DeclRefExpr
198   Cell k = make_cell();               CallExpr
```

Each `ignoring*` matcher peels a particular set of wrappers before applying its inner matcher. The examples all use `varDecl(hasAncestor(functionDecl(hasName("ignoring"))), hasInitializer(...))` so only these twelve variables count.

| Matcher | Implicit casts | Parentheses | Explicit casts | Implicit ctor / temporaries |
|---------|----------------|-------------|----------------|-----------------------------|
| `ignoringImpCasts` | yes | no | no | no |
| `ignoringParens` | no | yes | no | no |
| `ignoringParenImpCasts` | yes | yes | no | partly (materialised temporaries) |
| `ignoringParenCasts` | yes | yes | yes | no |
| `ignoringImplicit` | yes | no | no | yes (temporaries, cleanups) |
| `ignoringElidableConstructorCall` | — | — | — | pre-C++17 elidable copies |

With `set traversal IgnoreUnlessSpelledInSource` the matcher framework peels implicit casts, parentheses, implicit copy constructors and materialised temporaries *everywhere*, so most of these become unnecessary — the last example of this section shows that.

### `ignoringImpCasts(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Strips implicit casts only. Parentheses and explicit casts stay.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringImpCasts(integerLiteral())))
```

**Expected:** 1 match — `a` at line 188. `b` is not matched: its parentheses are in the way.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringImpCasts(declRefExpr())))
```

**Expected:** 1 match — `c` at line 190. `d` (line 191) is blocked by its parentheses.

### `ignoringParens(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Strips parentheses only. Note that `char b = (0)` still has an implicit cast *outside* the parentheses, so this alone does not reach the literal.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringParens(integerLiteral())))
```

**Expected:** 1 match — `a` at line 188.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringParens(implicitCastExpr())))
```

**Expected:** 4 matches — `b`, `c`, `d` and `f` (lines 189, 190, 191, 193): the initializers whose outermost node is an implicit cast.

### `ignoringParenImpCasts(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Strips parentheses *and* implicit casts, in any interleaving. Explicit casts stay.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringParenImpCasts(integerLiteral())))
```

**Expected:** 2 matches — `a` (line 188) and `b` (line 189).

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringParenImpCasts(declRefExpr())))
```

**Expected:** 2 matches — `c` (line 190) and `d` (line 191). `e` and `f` keep their explicit casts and stay out.

### `ignoringParenCasts(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Strips parentheses and *every* kind of cast — implicit, C-style, functional and the C++ named casts.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringParenCasts(integerLiteral())))
```

**Expected:** 5 matches — `a`, `b`, `e`, `f` and `g` (lines 188, 189, 192, 193, 194).

### `ignoringImplicit(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Strips every *implicit* node — implicit casts, materialised temporaries, `ExprWithCleanups`, `ConstantExpr` — but not parentheses. This is the one used earlier for case constants and range-`for` initialisers. Since C++17 there is no implicit node around `Cell()` or `make_cell()`, so on this sample it reports the same as the plain matcher.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringImplicit(cxxConstructExpr())))
```

**Expected:** 3 matches — `h`, `i` and `j` (lines 195, 196, 197).

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringImplicit(declRefExpr())))
```

**Expected:** 1 match — `c` at line 190.

### `ignoringElidableConstructorCall(Matcher<Expr> InnerMatcher)` — Matcher<Expr>

Before C++17, `Cell k = make_cell();` had an *elidable* copy constructor call around the `CallExpr`, plus the bookkeeping nodes that go with it. Since C++17 the standard guarantees elision and the AST has only the `CallExpr`. This matcher skips the pre-C++17 nodes so one matcher works in every language mode. Try it on the tiny second sample in both modes:

```clang-query
# sample: manifests/trav_elidable.cpp -std=c++14
match varDecl(hasInitializer(callExpr()))
```

**Expected:** 0 matches — in C++14 the initializer of `H D = G();` is a `CXXConstructExpr`, not the call.

```clang-query
# sample: manifests/trav_elidable.cpp -std=c++14
match varDecl(hasInitializer(ignoringElidableConstructorCall(callExpr())))
```

**Expected:** 1 match — `D` at `trav_elidable.cpp:7`, with the elidable copy skipped.

```clang-query
# sample: manifests/trav_elidable.cpp -std=c++23
match varDecl(hasInitializer(ignoringElidableConstructorCall(callExpr())))
```

**Expected:** 1 match — the same `D`; in C++23 there is nothing to skip and the matcher is transparent.

```clang-query
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(ignoringElidableConstructorCall(callExpr())))
```

**Expected:** 1 match — `k` at line 198 of the main sample.

Finally, the whole family at once, replaced by a traversal mode:

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasAncestor(functionDecl(hasName("ignoring"))),
              hasInitializer(declRefExpr()))
```

**Expected:** 3 matches — `c`, `d` and `j` (lines 190, 191, 197). No `ignoring*` needed: the implicit casts, the parentheses around `arr` and even the implicit copy constructor of `j` are all invisible in this mode.

---

## 9.6 — Casts

### `hasSourceExpression(Matcher<Expr> InnerMatcher)` — Matcher<CastExpr>, Matcher<OpaqueValueExpr>

Matches the expression a cast is applied to — for any cast node, implicit or explicit. The `OpaqueValueExpr` overload is for the placeholder Clang uses when one expression is referenced from two places, as in the GNU `a ?: b` where the condition is also the result.

```clang-query
match castExpr(hasSourceExpression(cxxConstructExpr(hasType(asString("Url")))))
```

**Expected:** 1 match — the implicit `ConstructorConversion` cast in `Url home = "https://example.test";` at line 203: a string literal converted through `Url(const char*)`.

```clang-query
match castExpr(hasSourceExpression(integerLiteral(equals(0))))
```

**Expected:** 3 matches — `(long)0l` (line 192), `reinterpret_cast<char*>(0)` (line 193) and `char(0)` (line 194).

```clang-query
match implicitCastExpr(hasSourceExpression(ignoringParens(stringLiteral())))
```

**Expected:** 3 matches — the array-to-pointer decays of `"w"` (line 51), of the `Url` initializer (line 203) and of `("my-string")` (line 204). Without `ignoringParens` the last one drops out.

```clang-query
match opaqueValueExpr(hasSourceExpression(ignoringImpCasts(
    declRefExpr(to(parmVarDecl(hasName("n")))))))
```

**Expected:** 2 matches — both at line 132. The single `OpaqueValueExpr` for `n` in `n ?: 7` is visited twice: once as the condition, once as the true branch.

---

## 9.7 — `new`, `delete` & initializer lists

### `hasArraySize(Matcher<Expr> InnerMatcher)` — Matcher<CXXNewExpr>

Matches the size expression of an array `new`. The size is converted to `size_t`, so in `AsIs` mode the literal sits under an `ImplicitCastExpr <IntegralCast>`.

```clang-query
match cxxNewExpr(hasArraySize(ignoringImpCasts(integerLiteral(equals(10)))))
```

**Expected:** 1 match — `new Thing[10]` at line 214.

```clang-query
match cxxNewExpr(hasArraySize(integerLiteral(equals(10))))
```

**Expected:** 0 matches — the integral cast is in the way; the reference's example only works with implicit nodes hidden.

### `hasPlacementArg(unsigned Index, Matcher<Expr> InnerMatcher)` — Matcher<CXXNewExpr>

Matches the N-th placement argument — the expressions in parentheses between `new` and the type, which are passed to `operator new` after the size.

```clang-query
match cxxNewExpr(hasPlacementArg(0, ignoringImpCasts(declRefExpr(to(varDecl(hasName("storage")))))))
```

**Expected:** 2 matches — `new (storage) Thing()` at line 215 and `new (storage, 16) Thing()` at line 216.

```clang-query
match cxxNewExpr(hasPlacementArg(1, integerLiteral(equals(16))))
```

**Expected:** 1 match — `new (storage, 16) Thing()` at line 216.

### `hasAnyPlacementArg(Matcher<Expr> InnerMatcher)` — Matcher<CXXNewExpr>

Matches if any placement argument matches; a plain `new` has none.

```clang-query
match cxxNewExpr(hasAnyPlacementArg(anything()))
```

**Expected:** 2 matches — the two placement `new` expressions at lines 215 and 216. `new Thing` and `new Thing[10]` (lines 213–214) are left out.

```clang-query
match cxxNewExpr(hasAnyPlacementArg(integerLiteral(equals(16))))
```

**Expected:** 1 match — line 216.

### `hasInit(unsigned N, Matcher<Expr> InnerMatcher)` — Matcher<InitListExpr>

Matches the N-th element of a braced initializer list.

```clang-query
match initListExpr(hasInit(2, integerLiteral()))
```

**Expected:** 1 match — `{1, 2, 3}` at line 219, the only list in the sample with a third element.

```clang-query
match initListExpr(hasInit(0, integerLiteral(equals(4))))
```

**Expected:** 1 match — `{.first = 4, .second = 5}` at line 220. Designators disappear in the *semantic* form that is traversed; element 0 is just `4`.

```clang-query
match initListExpr(hasInit(1, initListExpr()))
```

**Expected:** 1 match — `int box[2][2] = {1, 2, 3, 4}` at line 221. Brace elision was undone: the semantic list holds two nested `int[2]` lists, and this matches the outer one.

### `hasSyntacticForm(Matcher<Expr> InnerMatcher)` — Matcher<InitListExpr>

Every initializer list exists in two forms: the **syntactic** one (exactly what was typed) and the **semantic** one (designators resolved, braces un-elided, fillers added). The tree walk visits the semantic form; `hasSyntacticForm` lets you inspect what the programmer actually wrote.

```clang-query
match initListExpr(hasSyntacticForm(initListExpr(hasInit(3, expr()))))
```

**Expected:** 1 match — the `box` list at line 221: syntactically it has four elements, semantically two.

```clang-query
match initListExpr(hasSyntacticForm(initListExpr(hasInit(0, designatedInitExpr()))))
```

**Expected:** 1 match — the `named` list at line 220: only the syntactic form still contains the `.first = 4` designator.

---

## 9.8 — Lambdas

A `LambdaExpr` owns a list of `LambdaCapture`s, explicit (`[x]`, `[&y]`, `[x = 1]`) or implicit (the ones `[=]` generates for every variable the body uses). Note that `lambdaCapture` is not a node you can match at top level — reach it through `hasAnyCapture` or `forEachLambdaCapture`.

### `hasAnyCapture(Matcher<LambdaCapture> InnerMatcher)` — Matcher<LambdaExpr>

Matches a lambda if any of its captures matches.

```clang-query
match lambdaExpr(hasAnyCapture(lambdaCapture()))
```

**Expected:** 4 matches — the lambdas on lines 228–231. The capture-less lambda on line 177 is not matched.

```clang-query
match lambdaExpr(hasAnyCapture(lambdaCapture(capturesVar(hasName("y")))))
```

**Expected:** 2 matches — `[=]` at line 230 (implicit capture of `y`) and `[&y]` at line 231.

### `forEachLambdaCapture(Matcher<LambdaCapture> InnerMatcher)` — Matcher<LambdaExpr>

Runs the inner matcher on every capture, producing one match per capture — provided the capture (or something inside it) is bound. In `IgnoreUnlessSpelledInSource` mode implicit captures are skipped.

```clang-query
match lambdaExpr(forEachLambdaCapture(
    lambdaCapture(capturesVar(varDecl(hasType(isInteger())))).bind("cap")))
```

**Expected:** 5 matches — `[x]` (line 228), `[x = 1]` (line 229), `[=]` twice at line 230 (for `x` and for `y`; `z` is a `float`) and `[&y]` (line 231).

```clang-query
match lambdaExpr(forEachLambdaCapture(lambdaCapture(capturesVar(varDecl(hasType(isInteger()))))))
```

**Expected:** 4 matches — the same four lambdas, but line 230 only once: unbound, its two capture matches are indistinguishable.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match lambdaExpr(forEachLambdaCapture(
    lambdaCapture(capturesVar(varDecl(hasType(isInteger())))).bind("cap")))
```

**Expected:** 3 matches — lines 228, 229 and 231. The implicit captures of `[=]` are not "spelled in source" and vanish.

### `capturesVar(Matcher<ValueDecl> InnerMatcher)` — Matcher<LambdaCapture>

Matches a capture by the variable it captures. For an init-capture like `[x = 1]` that variable is the synthesised one declared in the capture itself.

```clang-query
match lambdaExpr(hasAnyCapture(lambdaCapture(capturesVar(hasName("x")))))
```

**Expected:** 3 matches — `[x]` (line 228), `[x = 1]` (line 229, the init-capture variable is also named `x`) and `[=]` (line 230).

```clang-query
match lambdaExpr(hasAnyCapture(lambdaCapture(capturesVar(
    varDecl(hasInitializer(integerLiteral(equals(1))))))))
```

**Expected:** 3 matches — lines 228 and 230 capture the outer `int x = 1`, and line 229's init-capture has the initializer `1` of its own.

---

## 9.9 — `sizeof` / `alignof`

`sizeof(x)`, `sizeof(T)`, `alignof(T)` and friends are all one node kind, `UnaryExprOrTypeTraitExpr`. `sizeOfExpr` and `alignOfExpr` are convenience matchers that select one operator; `hasArgumentOfType` looks at the type of the operand, whether it was written as a type or as an expression.

### `sizeOfExpr(Matcher<UnaryExprOrTypeTraitExpr> InnerMatcher)` — Matcher<Stmt>

Matches a `sizeof` expression whose node matches the inner matcher.

```clang-query
match sizeOfExpr(hasArgumentOfType(asString("float")))
```

**Expected:** 1 match — `sizeof(b)` at line 239.

```clang-query
match sizeOfExpr(hasArgumentOfType(recordType()))
```

**Expected:** 1 match — `sizeof(Thing)` at line 240.

### `alignOfExpr(Matcher<UnaryExprOrTypeTraitExpr> InnerMatcher)` — Matcher<Stmt>

The same for `alignof`.

```clang-query
match alignOfExpr(hasArgumentOfType(asString("int")))
```

**Expected:** 1 match — `alignof(int)` at line 239.

```clang-query
match alignOfExpr(hasArgumentOfType(recordType(hasDeclaration(recordDecl(hasName("Thing"))))))
```

**Expected:** 1 match — `alignof(Thing)` at line 240.

### `hasArgumentOfType(Matcher<QualType> InnerMatcher)` — Matcher<UnaryExprOrTypeTraitExpr>

Matches by the type of the operand. `sizeof(a)` with `int a` and `alignof(int)` both have argument type `int`.

```clang-query
match unaryExprOrTypeTraitExpr(hasArgumentOfType(asString("int")))
```

**Expected:** 2 matches — `sizeof(a)` and `alignof(int)` at line 239.

```clang-query
match unaryExprOrTypeTraitExpr(hasArgumentOfType(asString("Thing")))
```

**Expected:** 2 matches — `sizeof(Thing)` and `alignof(Thing)` at line 240.

---

## 9.10 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| `callee` has two overloads | `callee(functionDecl(...))` finds the declaration; `callee(memberExpr())` sees the callee expression, casts and all |
| `hasArgument` peels, `hasAnyArgument` does not | `hasAnyArgument(declRefExpr())` found nothing until wrapped in `ignoringImpCasts` |
| `forEach*` needs `.bind()` | `forEachSwitchCase(switchCase())` reported 3, `.bind("c")` reported 5 |
| `on` vs `onImplicitObjectArgument` vs `thisPointerType` | 3, 4 and 5 matches for the same `Counter` calls, depending on what is peeled and whether pointers are looked through |
| One operand matcher, five node kinds | `hasLHS` worked on `binaryOperator`, `cxxOperatorCallExpr`, `cxxRewrittenBinaryOperator`, `cxxFoldExpr` and `arraySubscriptExpr` |
| Init-statement ≠ condition variable | `hasInitStatement` matched line 127, `hasConditionVariableStatement` matched line 128 |
| Coroutines have a body inside a body | `hasBody(coroutineBodyStmt(hasBody(compoundStmt())))` |
| `ignoring*` each peel a different set | one function, twelve variables, six matchers, six different counts |
| `IgnoreUnlessSpelledInSource` replaces most of them | `hasInitializer(declRefExpr())` found `c`, `d` and `j` with nothing else |
| Case constants and array sizes carry hidden casts | `ConstantExpr` around `case 1`, `IntegralCast` around `new T[10]` |
| Initializer lists have two forms | `hasSyntacticForm` saw the four elements and the designator the tree walk does not |

**Quiz.** Find every member call in the sample that is made *on an object whose static type is `Sub`* but that *invokes a method declared in `Counter`* — i.e. calls that go through the derived-to-base conversion. You need a matcher from 9.1 for the object, and a `callee` with a narrowing matcher for the class that owns the method.

> [!hint]- Hint
> `on(...)` peels the derived-to-base cast, so it sees the object as a `Sub`. The `Matcher<Decl>` overload of `callee` accepts `cxxMethodDecl(ofClass(...))`.

> [!success]- Answer
> `cxxMemberCallExpr(on(hasType(cxxRecordDecl(hasName("Sub")))), callee(cxxMethodDecl(ofClass(hasName("Counter")))))` — 1 match, `s.bump()` at line 56. `s.extra()` is declared in `Sub`, and every other call has a `Counter` object.

---

[← Part 8 — Traversal Matchers I — Tree Navigation & Declarations](part_8_traversal_tree_decls.md) | [Part 10 — Traversal Matchers III — Types, TypeLocs & Templates →](part_10_traversal_types_templates.md)
