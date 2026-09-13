# Part 6 — Narrowing Matchers II — Statements & Expressions

[← Part 5 — Narrowing Matchers I — Logic & Declarations](part_5_narrowing_logic_decls.md) | [Part 7 — Narrowing Matchers III — Types, Templates & Source Locations →](part_7_narrowing_types_templates_locations.md)

**Sample:** `manifests/narrow_stmts.cpp` · flags: `-std=c++23`

## What You'll Learn
- How narrowing matchers plug into *statement* node matchers: operators, literals, calls, casts, member accesses, blocks, lambdas and `sizeof`.
- Why the same narrowing name (`hasOperatorName`, `isArrow`, `argumentCountIs`) exists for several node kinds, and how the return-type column tells you where it fits.
- The three shapes a `<` can take in the AST — `BinaryOperator`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` — and how each is narrowed.
- How operator names are spelled inside the DSL (`"+="`, `"<=>"`, `"[]"`, `"<<"`), how cast kinds and trait kinds are spelled (`"CK_…"`, `"UETT_…"`), and which literal values `equals` accepts.
- How to use a bound node from *outside* a template to narrow a dependent member access (`memberHasSameNameAsBoundNode`).

## The Big Picture

Part 5 narrowed *declarations* (is it static? virtual? named `foo`?). This
part narrows *statements and expressions*: the things that live inside
function bodies. A narrowing matcher never moves to another node — it looks
at the node it is handed and answers yes or no. What changes here is the
*kind* of node it is handed, so the reference's return-type column decides
which node matcher it can sit inside:

```
node matcher            narrowing matcher       return type in the reference
─────────────────────── ─────────────────────── ────────────────────────────
binaryOperator(         hasOperatorName("+=") ) Matcher<BinaryOperator>
cxxOperatorCallExpr(    hasOperatorName("+=") ) Matcher<CXXOperatorCallExpr>
cxxFoldExpr(            hasOperatorName("+")  ) Matcher<CXXFoldExpr>
unaryOperator(          hasOperatorName("-")  ) Matcher<UnaryOperator>
```

One name, several homes. If you put `hasOperatorName` inside `callExpr()`
clang-query refuses it, because no row of the reference says
`Matcher<CallExpr>` for that name.

The operator family is the trickiest because C++ spells one operation three
ways in the AST:

```
 a < b     ints                 BinaryOperator             opcode "<"
 v1 < v2   class with operator< CXXOperatorCallExpr        callee operator<  (also a CallExpr!)
 a < b     class with <=>       CXXRewrittenBinaryOperator "<"  ==  (a <=> b) < 0
```

Operator names are passed as plain strings exactly as you would type them
in source: `"+="`, `"<=>"`, `"<<"`, `"[]"`, `"()"`. Enumerators that the
C++ API takes bare (`CK_NullToPointer`, `UETT_SizeOf`) are passed as quoted
strings in clang-query: `hasCastKind("CK_NullToPointer")`,
`ofKind("UETT_SizeOf")`.

The sample has a hand-written `std::strong_ordering` (no `#include`), a
`Vec2` class with overloaded operators, a `Version` class with `<=>`,
variadic templates for fold expressions, and dependent code for the
template-only member matchers.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/narrow_stmts.cpp -- -std=c++23
```

---

## 6.1 — Operators

Everything in this group narrows on the *operator* of an expression node.
`BinaryOperator` and `UnaryOperator` are built-in operators on built-in
types. `CXXOperatorCallExpr` is a call to an overloaded operator (it is a
`CallExpr` underneath). `CXXRewrittenBinaryOperator` is a comparison that
the compiler rewrote in terms of `<=>` or `==`. `CXXFoldExpr` is a C++17
fold over a parameter pack.

### `hasOperatorName(std::string Name)` — Matcher<BinaryOperator>, Matcher<CXXFoldExpr>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>, Matcher<UnaryOperator>

Matches an operator expression (or fold expression) whose operator is
spelled exactly `Name`. Compound assignments are their own spelling, so
`"+="` is not `"+"`.

```text
clang-query> match binaryOperator(hasOperatorName("+="))
```

**Expected:** 1 match — `r += a * b` at `narrow_stmts.cpp:47`.

Unary operators use the same names; the minus in `-13` is a `UnaryOperator`
wrapped around the literal `13`:

```text
clang-query> match unaryOperator(hasOperatorName("-"))
```

**Expected:** 2 matches — `-a` at `narrow_stmts.cpp:54` and `-13` at `narrow_stmts.cpp:111`.

For an overloaded operator the name is what was written between the
operands, not `operator<<`:

```text
clang-query> match cxxOperatorCallExpr(hasOperatorName("<<"))
```

**Expected:** 1 match — `log << 7` at `narrow_stmts.cpp:69`.

A rewritten comparison keeps the operator the programmer wrote:

```text
clang-query> match cxxRewrittenBinaryOperator(hasOperatorName("<"))
```

**Expected:** 1 match — `a < b` on `Version` at `narrow_stmts.cpp:74`.

Underneath, every rewritten comparison is a call to `operator<=>` followed
by a comparison against `0`, so asking for `<=>` calls finds the three
hidden ones plus the explicit `a <=> b`:

```text
clang-query> match cxxOperatorCallExpr(hasOperatorName("<=>"))
```

**Expected:** 4 matches — inside `a < b`, `a > b`, `a <= b` (`narrow_stmts.cpp:74`–`76`) and the explicit `a <=> b` at `narrow_stmts.cpp:78`.

Fold expressions carry the folded operator:

```text
clang-query> match cxxFoldExpr(hasOperatorName("+"))
```

**Expected:** 1 match — `(0 + ... + args)` at `narrow_stmts.cpp:84`.

### `hasAnyOperatorName(StringRef, ..., StringRef)` — Matcher<BinaryOperator>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>, Matcher<UnaryOperator>

Shorthand for `anyOf(hasOperatorName(a), hasOperatorName(b), …)`. It takes
any number of names.

```text
clang-query> match binaryOperator(hasAnyOperatorName("&&", "||"))
```

**Expected:** 5 matches — `eq && lt` at `narrow_stmts.cpp:52` and the four `||` of the return at `narrow_stmts.cpp:79`.

```text
clang-query> match unaryOperator(hasAnyOperatorName("++", "--"))
```

**Expected:** 2 matches — `++r` at `narrow_stmts.cpp:55` and `r--` at `narrow_stmts.cpp:56`.

```text
clang-query> match cxxOperatorCallExpr(hasAnyOperatorName("=", "+="))
```

**Expected:** 2 matches — `v1 = v2` and `v1 += v2` at `narrow_stmts.cpp:62`–`63`.

```text
clang-query> match cxxRewrittenBinaryOperator(hasAnyOperatorName("<=", "!="))
```

**Expected:** 2 matches — `a <= b` at `narrow_stmts.cpp:76` and `a != b` at `narrow_stmts.cpp:77` (rewritten as `!(a == b)`).

### `isAssignmentOperator()` — Matcher<BinaryOperator>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

Matches plain assignment and every compound assignment (`=`, `+=`, `-=`,
`*=`, …) without listing them.

```text
clang-query> match binaryOperator(isAssignmentOperator())
```

**Expected:** 4 matches — `r = …`, `r += …`, `r -= …` at `narrow_stmts.cpp:46`–`48` and the dependent `b.value = T()` at `narrow_stmts.cpp:196`.

```text
clang-query> match cxxOperatorCallExpr(isAssignmentOperator())
```

**Expected:** 2 matches — `v1 = v2` at `narrow_stmts.cpp:62` and `v1 += v2` at `narrow_stmts.cpp:63`.

The rewritten-operator overload exists for API symmetry, but a rewritten
operator is always a comparison, so it never matches:

```text
clang-query> match cxxRewrittenBinaryOperator(isAssignmentOperator())
```

**Expected:** 0 matches — nothing to find.

### `isComparisonOperator()` — Matcher<BinaryOperator>, Matcher<CXXOperatorCallExpr>, Matcher<CXXRewrittenBinaryOperator>

Matches `==`, `!=`, `<`, `>`, `<=`, `>=` and `<=>`.

```text
clang-query> match binaryOperator(isComparisonOperator())
```

**Expected:** 3 matches — `a == b`, `a < b`, `a >= b` at `narrow_stmts.cpp:49`–`51`.

```text
clang-query> match cxxRewrittenBinaryOperator(isComparisonOperator())
```

**Expected:** 4 matches — the four rewritten comparisons on `Version` at `narrow_stmts.cpp:74`–`77`.

Counting operator *calls* that are comparisons is larger than you might
guess: each rewritten `a < b` contains two calls (`operator<=>` and the
`operator<` on `std::strong_ordering`), plus the `Vec2` comparisons, the
explicit `<=>`, and `ord < 0`:

```text
clang-query> match cxxOperatorCallExpr(isComparisonOperator())
```

**Expected:** 11 matches — `v1 < v2`, `v1 == v2` (`narrow_stmts.cpp:64`–`65`), two per rewritten `<`/`>`/`<=` (`narrow_stmts.cpp:74`–`76`), `a != b` (`narrow_stmts.cpp:77`), `a <=> b` (`narrow_stmts.cpp:78`) and `ord < 0` (`narrow_stmts.cpp:79`).

### `hasOverloadedOperatorName(StringRef Name)` — Matcher<CXXOperatorCallExpr>, Matcher<FunctionDecl>

Matches by overloaded operator name written without the `operator` prefix.
On a call it is the same test as `hasOperatorName`; on a `FunctionDecl` it
lets you find the operator *definitions* themselves.

```text
clang-query> match cxxOperatorCallExpr(hasOverloadedOperatorName("[]"))
```

**Expected:** 1 match — `v1[0]` at `narrow_stmts.cpp:70`.

```text
clang-query> match functionDecl(hasOverloadedOperatorName("<"))
```

**Expected:** 2 matches — the hidden-friend `operator<` of the `strong_ordering` stub at `narrow_stmts.cpp:10` and `Vec2::operator<` at `narrow_stmts.cpp:26`.

Combined with a traversal matcher it finds the class that *has* an
operator:

```text
clang-query> match cxxRecordDecl(hasMethod(hasOverloadedOperatorName("*")))
```

**Expected:** 1 match — `Vec2` at `narrow_stmts.cpp:19`.

### `hasAnyOverloadedOperatorName(StringRef, ..., StringRef)` — Matcher<CXXOperatorCallExpr>, Matcher<FunctionDecl>

`anyOf` over several overloaded operator names.

```text
clang-query> match cxxOperatorCallExpr(hasAnyOverloadedOperatorName("[]", "<<"))
```

**Expected:** 2 matches — `log << 7` at `narrow_stmts.cpp:69` and `v1[0]` at `narrow_stmts.cpp:70`.

```text
clang-query> match functionDecl(hasAnyOverloadedOperatorName("<", ">", "<=>"))
```

**Expected:** 4 matches — stub `operator<` and `operator>` at `narrow_stmts.cpp:10`–`11`, `Vec2::operator<` at `narrow_stmts.cpp:26`, `Version::operator<=>` at `narrow_stmts.cpp:41`.

### `isBinaryFold()` — Matcher<CXXFoldExpr>

A binary fold has an initializer next to the pack: `(0 + ... + args)` or
`(args * ... * 1)`.

```text
clang-query> match cxxFoldExpr(isBinaryFold())
```

**Expected:** 2 matches — `sum` at `narrow_stmts.cpp:84` and `product` at `narrow_stmts.cpp:88`.

### `isUnaryFold()` — Matcher<CXXFoldExpr>

A unary fold has only the pack and the operator: `(args && ...)` or
`(... || args)`.

```text
clang-query> match cxxFoldExpr(isUnaryFold())
```

**Expected:** 2 matches — `all_of` at `narrow_stmts.cpp:92` and `any_of` at `narrow_stmts.cpp:96`.

### `isLeftFold()` — Matcher<CXXFoldExpr>

Left folds have the `...` on the left of the pack: `(0 + ... + args)` and
`(... || args)`. Left/right is independent of unary/binary.

```text
clang-query> match cxxFoldExpr(isLeftFold())
```

**Expected:** 2 matches — `sum` at `narrow_stmts.cpp:84` and `any_of` at `narrow_stmts.cpp:96`.

### `isRightFold()` — Matcher<CXXFoldExpr>

Right folds have the pack on the left of the `...`: `(args * ... * 1)` and
`(args && ...)`.

```text
clang-query> match cxxFoldExpr(isRightFold())
```

**Expected:** 2 matches — `product` at `narrow_stmts.cpp:88` and `all_of` at `narrow_stmts.cpp:92`.

The two axes combine freely:

```text
clang-query> match cxxFoldExpr(isUnaryFold(), isLeftFold())
```

**Expected:** 1 match — `(... || args)` at `narrow_stmts.cpp:96`.

## 6.2 — Literals

Literal node matchers (`integerLiteral()`, `floatLiteral()`,
`characterLiteral()`, `cxxBoolLiteral()`) accept one narrowing matcher for
their value, and there is one expression-level test for "is this a null
pointer".

### `equals(ValueT Value)` — Matcher<CXXBoolLiteralExpr>, Matcher<CharacterLiteral>, Matcher<FloatingLiteral>, Matcher<IntegerLiteral>

Matches a literal whose value equals `Value`. In clang-query the argument
is a bare literal: `true`/`false`, an integer, or a floating number. There
is no character-literal syntax, so a `CharacterLiteral` is compared by its
code point (`97` for `'a'`), and integer suffixes such as `42u` are not
accepted by the parser.

```text
clang-query> match cxxBoolLiteral(equals(true))
```

**Expected:** 1 match — `true` at `narrow_stmts.cpp:102`.

`0`/`1` also work for booleans:

```text
clang-query> match cxxBoolLiteral(equals(0))
```

**Expected:** 1 match — `false` at `narrow_stmts.cpp:103`.

```text
clang-query> match characterLiteral(equals(97))
```

**Expected:** 1 match — `'a'` at `narrow_stmts.cpp:104`.

```text
clang-query> match characterLiteral(equals(0))
```

**Expected:** 1 match — `'\0'` at `narrow_stmts.cpp:105`.

Floating values compare numerically, so any spelling of the same number
works:

```text
clang-query> match floatLiteral(equals(3.14))
```

**Expected:** 1 match — `3.14` at `narrow_stmts.cpp:106`.

```text
clang-query> match floatLiteral(equals(314e-2))
```

**Expected:** 1 match — the same `3.14` at `narrow_stmts.cpp:106`.

Integer literals compare by value regardless of type or suffix:

```text
clang-query> match integerLiteral(equals(42))
```

**Expected:** 3 matches — `42` at `narrow_stmts.cpp:109`, `42LL` at `narrow_stmts.cpp:112` and the argument of `y(42)` at `narrow_stmts.cpp:164`.

A negative number is not a literal: the minus is a `UnaryOperator` whose
operand is the positive literal. Match the operator and narrow its operand:

```text
clang-query> match unaryOperator(hasOperatorName("-"),
                                 hasUnaryOperand(integerLiteral(equals(13))))
```

**Expected:** 1 match — `-13` at `narrow_stmts.cpp:111`.

### `nullPointerConstant()` — Matcher<Expr>

Matches an expression that is a null pointer constant: `nullptr`, GNU
`__null`, or a literal `0` that sits directly under a pointer-typed cast.
A `0` used as an `int` is *not* matched, which is what makes this the
right tool for "replace 0 with nullptr" checks.

```text
clang-query> match expr(nullPointerConstant())
```

**Expected:** 5 matches — `nullptr` at `narrow_stmts.cpp:117`, `__null` at `narrow_stmts.cpp:118`, the `0` of `(char *)0` at `narrow_stmts.cpp:119`, `int *ip = 0` at `narrow_stmts.cpp:120` and again at `narrow_stmts.cpp:180`; `int n = 0` is not matched.

The initializer of a pointer variable is an implicit cast *around* the
constant, so to go from the variable you must look through it:

```text
clang-query> match varDecl(hasInitializer(ignoringImplicit(nullPointerConstant())))
```

**Expected:** 4 matches — `v2`, `v3`, `ip` at `narrow_stmts.cpp:117`, `118`, `120` and `ip` at `narrow_stmts.cpp:180` (`cp` is excluded: its initializer is an explicit C-style cast).

## 6.3 — Calls & construction

Argument counts, lookup rules and initialization style. Remember that a
`CXXOperatorCallExpr` is a `CallExpr` with two (binary) or one (unary)
argument, so plain `callExpr(argumentCountIs(2))` also picks up every
`v1 < v2`; the examples exclude them with `unless`.

### `argumentCountIs(unsigned N)` — Matcher<CXXConstructExpr>, Matcher<CXXUnresolvedConstructExpr>, Matcher<CallExpr>

Matches a call or constructor call with exactly `N` arguments. Absent
default arguments still count, so `fd(1)` with `void fd(int, int = 0)` has
two.

```text
clang-query> match callExpr(argumentCountIs(2), unless(cxxOperatorCallExpr()))
```

**Expected:** 2 matches — `f2(0, 0)` at `narrow_stmts.cpp:143` and `fd(1)` at `narrow_stmts.cpp:145`.

```text
clang-query> match cxxConstructExpr(argumentCountIs(2))
```

**Expected:** 3 matches — `Pt c(1, 2)`, `Pt d{3, 4}`, `Pt e = {5, 6}` at `narrow_stmts.cpp:148`–`150`.

Inside a template, `T(1, 2)` with `T` unknown is a
`CXXUnresolvedConstructExpr`:

```text
clang-query> match cxxUnresolvedConstructExpr(argumentCountIs(2))
```

**Expected:** 1 match — `T(1, 2)` at `narrow_stmts.cpp:197`.

### `argumentCountAtLeast(unsigned N)` — Matcher<CXXConstructExpr>, Matcher<CXXUnresolvedConstructExpr>, Matcher<CallExpr>

Same counting rule, with `>= N`.

```text
clang-query> match callExpr(argumentCountAtLeast(2), unless(cxxOperatorCallExpr()))
```

**Expected:** 3 matches — `f2(0, 0)`, `f3(0, 0, 0)`, `fd(1)` at `narrow_stmts.cpp:143`–`145`.

```text
clang-query> match cxxConstructExpr(argumentCountAtLeast(2))
```

**Expected:** 3 matches — the two-argument `Pt` constructions at `narrow_stmts.cpp:148`–`150`.

```text
clang-query> match cxxUnresolvedConstructExpr(argumentCountAtLeast(1))
```

**Expected:** 1 match — `T(1, 2)` at `narrow_stmts.cpp:197` (`T()` at `narrow_stmts.cpp:196` has zero arguments).

### `usesADL()` — Matcher<CallExpr>

Matches a call whose callee was found *only* by argument-dependent lookup.
`y(x)` with `x` of type `NS::X` finds `NS::y` through ADL; `NS::y(x)` is
qualified and `y(42)` is found by ordinary lookup. The hidden-friend
comparison operators of the `strong_ordering` stub are also reachable only
through ADL, so the rewritten `Version` comparisons show up too.

```text
clang-query> match callExpr(usesADL())
```

**Expected:** 5 matches — `y(x)` at `narrow_stmts.cpp:162` plus the `strong_ordering` friend calls hidden inside `a < b`, `a > b`, `a <= b` (`narrow_stmts.cpp:74`–`76`) and `ord < 0` at `narrow_stmts.cpp:79`.

### `isListInitialization()` — Matcher<CXXConstructExpr>

Matches a constructor call written with braces, whether direct (`Pt d{3, 4}`)
or copy-list (`Pt e = {5, 6}`).

```text
clang-query> match cxxConstructExpr(isListInitialization())
```

**Expected:** 2 matches — `Pt d{3, 4}` at `narrow_stmts.cpp:149` and `Pt e = {5, 6}` at `narrow_stmts.cpp:150`.

### `requiresZeroInitialization()` — Matcher<CXXConstructExpr>

Matches a constructor call that must zero the object first: value
initialization of a class with a trivial default constructor, such as
`Point()`.

```text
clang-query> match cxxConstructExpr(requiresZeroInitialization())
```

**Expected:** 1 match — `Point()` at `narrow_stmts.cpp:151`.

### `isArray()` — Matcher<CXXNewExpr>

Matches `new T[n]` as opposed to `new T` / `new T(args)`.

```text
clang-query> match cxxNewExpr(isArray())
```

**Expected:** 2 matches — `new int[10]` at `narrow_stmts.cpp:168` and `new Pt[3]` at `narrow_stmts.cpp:170`.

```text
clang-query> match cxxNewExpr(unless(isArray()))
```

**Expected:** 1 match — `new int(5)` at `narrow_stmts.cpp:169`.

## 6.4 — Casts

Every conversion, implicit or explicit, is a `CastExpr` carrying a *cast
kind*. The kind names are Clang's `CK_…` enumerators, passed as strings.

### `hasCastKind(CastKind Kind)` — Matcher<CastExpr>

Matches a cast whose kind is `Kind`, spelled `"CK_<Name>"`.

```text
clang-query> match castExpr(hasCastKind("CK_IntegralToFloating"))
```

**Expected:** 1 match — the implicit `int` → `double` in `double widened = n` at `narrow_stmts.cpp:176`.

```text
clang-query> match castExpr(hasCastKind("CK_FloatingToIntegral"))
```

**Expected:** 1 match — `int narrowed = d` at `narrow_stmts.cpp:177`.

```text
clang-query> match castExpr(hasCastKind("CK_NullToPointer"))
```

**Expected:** 5 matches — the implicit casts around `nullptr`, `__null`, the `0` of `(char *)0`, and both `int *ip = 0` (`narrow_stmts.cpp:117`–`120`, `180`).

```text
clang-query> match castExpr(hasCastKind("CK_BitCast"))
```

**Expected:** 1 match — `int *` → `void *` in `void *vp = &n` at `narrow_stmts.cpp:181`.

Explicit casts often do less than they look: `static_cast<long>(n)` is a
`CXXStaticCastExpr` of kind `CK_NoOp` whose *child* implicit cast carries
the real `CK_IntegralCast`.

```text
clang-query> match cxxStaticCastExpr(hasCastKind("CK_IntegralCast"))
```

**Expected:** 0 matches — the static cast node itself is `CK_NoOp`.

```text
clang-query> match cxxStaticCastExpr(has(implicitCastExpr(hasCastKind("CK_IntegralCast"))))
```

**Expected:** 1 match — `static_cast<long>(n)` at `narrow_stmts.cpp:178`.

## 6.5 — Members & names

Member access comes in three node kinds. `MemberExpr` is a resolved
`obj.m` / `p->m`. Inside a template, `b.reset()` where `b` has a dependent
type cannot be resolved, so it is a `CXXDependentScopeMemberExpr`; and a
call to an *overloaded* member with dependent arguments is an
`UnresolvedMemberExpr`. Two of the matchers here only make sense for
dependent code, where `hasDeclaration` has nothing to point at.

### `isArrow()` — Matcher<CXXDependentScopeMemberExpr>, Matcher<MemberExpr>, Matcher<UnresolvedMemberExpr>

Matches member accesses written with `->` rather than `.`. An access
through the implicit `this` (`width` alone inside a method, or `count`
inside a lambda that captured `this`) counts as `->`.

```text
clang-query> match memberExpr(isArrow())
```

**Expected:** 5 matches — `this->width` and bare `width` at `narrow_stmts.cpp:209`, `pp->width` at `narrow_stmts.cpp:212`, and `count` inside the two `this`-capturing lambdas at `narrow_stmts.cpp:241`–`242`.

```text
clang-query> match cxxDependentScopeMemberExpr(isArrow())
```

**Expected:** 1 match — `p->reset()` at `narrow_stmts.cpp:195`.

```text
clang-query> match unresolvedMemberExpr(isArrow())
```

**Expected:** 2 matches — `this->print(v)` and `print(v)` at `narrow_stmts.cpp:206`–`207`.

### `hasMemberName(std::string N)` — Matcher<CXXDependentScopeMemberExpr>

A dependent member has no declaration to name, but its spelling is known.
This matches on that spelling.

```text
clang-query> match cxxDependentScopeMemberExpr(hasMemberName("reset"))
```

**Expected:** 2 matches — `b.reset()` and `p->reset()` at `narrow_stmts.cpp:194`–`195`.

### `memberHasSameNameAsBoundNode(std::string BindingID)` — Matcher<CXXDependentScopeMemberExpr>

Compares the dependent member's name with the name of a node already bound
under `BindingID` (a `VarDecl`, `FieldDecl` or `CXXMethodDecl`). The
`.bind` must happen *earlier in the same matcher*, so the usual shape is:
walk from the object expression's type to the class template, bind the
member you care about there, then compare. Here `b` has type `Box<T>`, a
`TemplateSpecializationType` whose declaration is the `Box` template:

```text
clang-query> match cxxDependentScopeMemberExpr(
               hasObjectExpression(hasType(templateSpecializationType(
                 hasDeclaration(classTemplateDecl(has(cxxRecordDecl(has(
                   cxxMethodDecl(hasName("reset")).bind("templMem"))))))))),
               memberHasSameNameAsBoundNode("templMem"))
```

**Expected:** 1 match — `b.reset()` at `narrow_stmts.cpp:194`, with `templMem` bound to `Box::reset` at `narrow_stmts.cpp:189` (`p->reset()` is excluded because `p` has pointer type, not the specialization type).

The same shape with a field instead of a method:

```text
clang-query> match cxxDependentScopeMemberExpr(
               hasObjectExpression(hasType(templateSpecializationType(
                 hasDeclaration(classTemplateDecl(has(cxxRecordDecl(has(
                   fieldDecl(hasName("value")).bind("f"))))))))),
               memberHasSameNameAsBoundNode("f"))
```

**Expected:** 1 match — `b.value` at `narrow_stmts.cpp:196`, with `f` bound to `Box::value` at `narrow_stmts.cpp:188`.

## 6.6 — Statements

Counting children of blocks, declaration statements and designated
initializers, plus the catch-all handler.

### `statementCountIs(unsigned N)` — Matcher<CompoundStmt>

Matches a `{ … }` block with exactly `N` direct child statements. The
default traversal also visits the implicit bodies Clang synthesizes for
defaulted special members (they are empty blocks), so switch to
`IgnoreUnlessSpelledInSource` to count only what is in the file:

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match compoundStmt(statementCountIs(0))
```

**Expected:** 1 match — the empty inner block at `narrow_stmts.cpp:217` (in the default traversal you would see 5, the extra four being implicit constructor bodies).

```text
clang-query> match compoundStmt(statementCountIs(3))
```

**Expected:** 3 matches — the bodies of `news` at `narrow_stmts.cpp:167`, the second block of `bodies` at `narrow_stmts.cpp:219`, and `traits` at `narrow_stmts.cpp:251`.

### `declCountIs(unsigned N)` — Matcher<DeclStmt>

Matches a declaration statement declaring exactly `N` names.

```text
clang-query> match declStmt(declCountIs(2))
```

**Expected:** 2 matches — `int a, b;` at `narrow_stmts.cpp:220` and `int d = 2, e;` at `narrow_stmts.cpp:222`.

### `designatorCountIs(unsigned N)` — Matcher<DesignatedInitExpr>

Matches a designated initializer element with exactly `N` designators.
Each element such as `[2].y = 1.0` is its own `DesignatedInitExpr` with
two designators (array index, then field). Array and nested designators are
C-only, so this example uses a small C sample:

```text
# sample: manifests/designators.c -std=c17
clang-query> match designatedInitExpr(designatorCountIs(2))
```

**Expected:** 5 matches — `[2].y`, `[0].x` at `designators.c:9` and `[2].y`, `[2].x`, `[0].x` at `designators.c:10`.

```text
# sample: manifests/designators.c -std=c17
clang-query> match designatedInitExpr(designatorCountIs(1))
```

**Expected:** 2 matches — `.x = 1.0` and `.y = 2.0` at `designators.c:11`.

### `isCatchAll()` — Matcher<CXXCatchStmt>

Matches `catch (...)` but not a typed handler.

```text
clang-query> match cxxCatchStmt(isCatchAll())
```

**Expected:** 1 match — `catch (...)` at `narrow_stmts.cpp:231`.

```text
clang-query> match cxxCatchStmt(unless(isCatchAll()))
```

**Expected:** 1 match — `catch (int)` at `narrow_stmts.cpp:229`.

## 6.7 — Lambdas

A lambda's capture list is a list of `LambdaCapture` nodes. They are not
top-level nodes (`match lambdaCapture(…)` is refused), so you always reach
them from `lambdaExpr()` through `hasAnyCapture`.

### `capturesThis()` — Matcher<LambdaCapture>

Matches a capture of `this`, explicit (`[this]`) or implicit (a `[&]` or
`[=]` lambda that uses a member).

```text
clang-query> match lambdaExpr(hasAnyCapture(lambdaCapture(capturesThis())))
```

**Expected:** 2 matches — `[this]() { return count; }` at `narrow_stmts.cpp:241` and `[&]() { return count; }` at `narrow_stmts.cpp:242`; the `[local]` lambda does not capture `this`.

## 6.8 — sizeof / alignof kind

`sizeof`, `alignof`, `__alignof` and `vec_step` all share one node,
`UnaryExprOrTypeTraitExpr`; the kind is the `UETT_…` enumerator, passed as
a string.

### `ofKind(UnaryExprOrTypeTrait Kind)` — Matcher<UnaryExprOrTypeTraitExpr>

Matches the trait expression of the given kind.

```text
clang-query> match unaryExprOrTypeTraitExpr(ofKind("UETT_SizeOf"))
```

**Expected:** 2 matches — `sizeof(x)` and `sizeof(double)` at `narrow_stmts.cpp:253`.

```text
clang-query> match unaryExprOrTypeTraitExpr(ofKind("UETT_AlignOf"))
```

**Expected:** 1 match — `alignof(int)` at `narrow_stmts.cpp:253`.

## 6.9 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Return type decides the home | `hasOperatorName` sits in five node matchers; `isArrow` in three; `argumentCountIs` in three |
| Three shapes of `<` | built-in `BinaryOperator`, overloaded `CXXOperatorCallExpr`, rewritten `CXXRewrittenBinaryOperator` |
| Operator calls are calls | `callExpr(argumentCountIs(2))` sees `v1 < v2`; `unless(cxxOperatorCallExpr())` filters them |
| Rewritten comparisons hide two calls | `hasOperatorName("<=>")` found 3 hidden `<=>` calls; `usesADL()` found the hidden-friend `<` |
| Spelling of enum arguments | `hasCastKind("CK_…")`, `ofKind("UETT_…")` as quoted strings |
| `equals` per literal kind | `true`/`0` for bools, code points for chars, numeric equality for floats, value for ints |
| Negative numbers | `unaryOperator("-")` + `hasUnaryOperand(integerLiteral(equals(13)))` |
| Dependent members | `hasMemberName` and `memberHasSameNameAsBoundNode` work where `hasDeclaration` cannot |
| Implicit nodes inflate counts | `IgnoreUnlessSpelledInSource` turned 5 empty blocks into the 1 you wrote |

**Quiz.** Which constructor calls in the sample pass exactly two arguments *and* use brace initialization? Write one matcher that returns only those.

> [!hint]- Hint
> Both facts are narrowing matchers on `CXXConstructExpr` from 6.3; a node matcher accepts several narrowers at once, and they are ANDed.

> [!success]- Answer
> `cxxConstructExpr(argumentCountIs(2), isListInitialization())` — 2 matches: `Pt d{3, 4}` at `narrow_stmts.cpp:149` and `Pt e = {5, 6}` at `narrow_stmts.cpp:150`.

---

[← Part 5 — Narrowing Matchers I — Logic & Declarations](part_5_narrowing_logic_decls.md) | [Part 7 — Narrowing Matchers III — Types, Templates & Source Locations →](part_7_narrowing_types_templates_locations.md)
