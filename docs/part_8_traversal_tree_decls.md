# Part 8 — Traversal Matchers I — Tree Navigation & Declarations

[← Part 7 — Narrowing Matchers III — Types, Templates & Source Locations](part_7_narrowing_types_templates_locations.md) | [Part 9 — Traversal Matchers II — Statements & Expressions →](part_9_traversal_stmts.md)

**Sample:** `manifests/trav_decls.cpp` · flags: `-std=c++23`

## What You'll Learn

- How a traversal matcher works: step from the current node to a *related*
  node, run an inner matcher there, and report the node you started from.
- The generic tree walkers — `has`, `hasDescendant`, `forEachDescendant`,
  `forEach`, `hasParent`, `hasAncestor` — and exactly how many matches each
  one produces.
- Why `forEachDescendant` only multiplies results when you `.bind()` inside
  it, and how implicit nodes (casts, injected class names, rewritten
  operators) change what a "parent" is.
- The declaration-side traversals: parameters and bodies of functions,
  classes of methods, bases of records, constructor initializers,
  initializers of variables and fields, structured bindings, declaration
  contexts and `using` declarations.
- Two reference names that clang-query 22 does not register (`traverse`,
  `findAll`) and the exact substitutes.

## The Big Picture

Parts 5–7 taught *narrowing* matchers: they look at one node and answer
yes/no. A **traversal** matcher instead says "go to a related node and ask
*that* node a question". The node that gets reported is still the outer one
you started from — unless you `.bind()` something inside, in which case the
inner node is reported too.

```text
        outer node  <------ this is what `match` prints
        |
        |  traversal matcher: has / hasParent / hasParameter / ofClass / ...
        v
        related node  <---- the inner matcher runs here
```

The relation can be structural or semantic:

```text
                 hasAncestor(...)  ^   ^
                                   |   |
        grand-parent --------------+   |  hasParent(...)  (one step up)
             |                         |
           parent ---------------------+
             |
         [ THIS NODE ]
           /      \
        child    child        has(...) / forEach(...)          (one step down)
         /                     \
   grand-child               grand-child   hasDescendant(...) /
                                           forEachDescendant(...)  (any depth)
```

Semantic traversals such as `ofClass`, `hasParameter(N, …)`,
`isDerivedFrom(…)` or `hasTargetDecl` do not walk the tree at all; they
follow a pointer stored in the node (the method's class, the N-th
parameter, the base classes, the target of a `using`). They read the same
way: *outer node, related node, inner matcher*.

One rule decides every count in this part. clang-query prints **one match
per distinct set of bound nodes**. `has`, `hasDescendant`, `hasParent` and
`hasAncestor` stop at the first success, so they yield one match per outer
node. `forEach`, `forEachDescendant`, `eachOf` and the `forEach…` family
try *every* candidate — but two results that bind exactly the same nodes
collapse into one line, so without an inner `.bind()` they count like their
`has…` siblings.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/trav_decls.cpp -- -std=c++23
```

The sample groups its declarations by section. Lines 5–8 hold nested
classes (`X`, `Y { X }`, `Z { Y { X } }`, and `Deep { B { C { D { E } } } }`),
lines 11–13 hold small functions and a `long widened = 7;` for the
parent/ancestor experiments, and everything from line 16 onward is named
after the matcher that uses it.

---

## 8.1 — The generic tree walkers

These matchers accept *any* node type (`Matcher<*>`) and move purely by tree
structure. Remember that `cxxRecordDecl` sees the **injected class name** —
every class `X` contains an implicit `CXXRecordDecl` also called `X` — so a
class can match "has a child named X" when it *is* X. Watch for it in the
counts below.

### `has(Matcher<*>)` — Matcher<*>

Matches a node that has a **direct child** matching the inner matcher; it
stops at the first child that does. With the reference's nested classes,
`X` matches through its injected class name, `Y` and `Z::Y` match through
their nested `X`, and `Z` does not (its `X` is two levels down).

```text
clang-query> match cxxRecordDecl(has(cxxRecordDecl(hasName("X"))))
```

**Expected:** 5 matches — `X` at `trav_decls.cpp:5`, `Y` and `Y::X` at `:6`, `Z::Y` and `Z::Y::X` at `:7`.

```text
clang-query> match cxxRecordDecl(hasName("Z"), has(cxxRecordDecl(hasName("X"))))
```

**Expected:** 0 matches — `Z`'s only `X` is a grandchild.

`has` is a *direct* matcher, so implicit wrapper nodes count as the child.
The initializer of `long widened = 7;` is an `ImplicitCastExpr` (int → long)
whose child is the literal, so the literal is not a direct child of the
variable.

```text
clang-query> match varDecl(hasName("widened"), has(integerLiteral()))
```

**Expected:** 0 matches — the direct child is the implicit cast, not the literal.

```text
clang-query> match varDecl(hasName("widened"),
                           has(expr(ignoringParenImpCasts(integerLiteral()))))
```

**Expected:** 1 match — `widened` at `trav_decls.cpp:13`.

### `hasDescendant(Matcher<*>)` — Matcher<*>

Matches a node with **any descendant** (child, grandchild, …) matching the
inner matcher. Like `has`, it stops at the first hit, so each outer node is
reported once. The only new match compared with `has` is `Z`.

```text
clang-query> match cxxRecordDecl(hasDescendant(cxxRecordDecl(hasName("X"))))
```

**Expected:** 6 matches — the 5 from `has` plus `Z` at `trav_decls.cpp:7`.

Even when you bind the descendant, `hasDescendant` binds only the *first*
one found. `Deep` has four nested class definitions, but you get one line.

```text
clang-query> match cxxRecordDecl(hasName("Deep"),
                                 hasDescendant(cxxRecordDecl(isDefinition()).bind("m")))
```

**Expected:** 1 match — `Deep` at `trav_decls.cpp:8`, with `m` bound to `Deep::B`.

### `forEachDescendant(Matcher<*>)` — Matcher<*>

Same walk as `hasDescendant`, but it produces a result for **every**
matching descendant instead of stopping at the first. Compare directly with
the block above — same outer node, same inner matcher, four lines instead of
one, each with a different `m`.

```text
clang-query> match cxxRecordDecl(hasName("Deep"),
                                 forEachDescendant(cxxRecordDecl(isDefinition()).bind("m")))
```

**Expected:** 4 matches — `Deep` at `trav_decls.cpp:8` four times, `m` bound to `B`, `C`, `D`, `E` in turn.

Drop the `.bind("m")` and the four results are indistinguishable (each binds
only `root` = `Deep`), so clang-query prints one line. This is the single
most common surprise with `forEach…`: *it multiplies matches only when the
inner matcher binds something.*

```text
clang-query> match cxxRecordDecl(hasName("Deep"),
                                 forEachDescendant(cxxRecordDecl(isDefinition())))
```

**Expected:** 1 match — `Deep` at `trav_decls.cpp:8`; the four results collapsed into one.

Nesting `forEachDescendant` inside `forEachDescendant` multiplies pairs.
Restricted to spelled classes, `Deep` yields (B→C, B→D, B→E, C→D, C→E, D→E).

```text
clang-query> match cxxRecordDecl(hasName("Deep"),
               forEachDescendant(cxxRecordDecl(unless(isImplicit()),
                 forEachDescendant(cxxRecordDecl(unless(isImplicit())).bind("m")))))
```

**Expected:** 6 matches — `Deep` at `trav_decls.cpp:8` six times, one per (outer, inner) pair.

Side by side, on `Deep` with inner matcher `cxxRecordDecl(isDefinition()).bind("m")`:

```text
has(...)                 -> 1   (B is the only direct child definition)
hasDescendant(...)       -> 1   (stops at B)
forEach(...)             -> 1   (B is the only direct child)
forEachDescendant(...)   -> 4   (B, C, D, E)
```

### `forEach(Matcher<*>)` — Matcher<*>

The one-level version of `forEachDescendant`: every **direct child** that
matches produces its own result. `Pair` has two fields; `has` reports the
class once, `forEach` reports it once per field.

```text
clang-query> match cxxRecordDecl(hasName("Pair"), forEach(fieldDecl().bind("f")))
```

**Expected:** 2 matches — `Pair` at `trav_decls.cpp:16` twice, `f` bound to `first` then `second`.

```text
clang-query> match cxxRecordDecl(hasName("Pair"), has(fieldDecl().bind("f")))
```

**Expected:** 1 match — `Pair` at `trav_decls.cpp:16`, `f` bound to `first` only.

### `hasParent(Matcher<*>)` — Matcher<*>

Matches a node whose **immediate parent** matches. The reference example:
the compound statement whose parent is an `if`.

```text
clang-query> match compoundStmt(hasParent(ifStmt()))
```

**Expected:** 1 match — `{ int v = 42; }` at `trav_decls.cpp:11`.

Parents include implicit nodes. The `42` and `43` in `int v = …` sit
directly under their `VarDecl`, but the `7` in `long widened = 7;` sits
under an `ImplicitCastExpr`, so in the default `AsIs` traversal it has no
`varDecl` parent.

```text
clang-query> match integerLiteral(hasParent(varDecl()))
```

**Expected:** 2 matches — `42` at `trav_decls.cpp:11` and `43` at `:12`.

```text
clang-query> match integerLiteral(hasParent(implicitCastExpr()))
```

**Expected:** 1 match — `7` at `trav_decls.cpp:13`.

Switch the traversal mode and the implicit cast disappears from the tree, so
the literal's parent becomes the variable.

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match integerLiteral(hasParent(varDecl()))
```

**Expected:** 3 matches — `42` at `trav_decls.cpp:11`, `43` at `:12`, and now `7` at `:13`.

### `hasAncestor(Matcher<*>)` — Matcher<*>

Matches a node with **any ancestor** matching; one result per node, like
`hasParent`. The reference example matches `42` inside the `if` but not `43`
inside the `for` — and here a second, invisible literal shows up: the
rewritten spaceship comparison `s1 < s2` on line 26 is really
`(s1 <=> s2) < 0`, and that `0` has an `if` ancestor too.

```text
clang-query> match integerLiteral(hasAncestor(ifStmt()))
```

**Expected:** 2 matches — `42` at `trav_decls.cpp:11` and the synthesized `0` at `:26`.

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match integerLiteral(hasAncestor(ifStmt()))
```

**Expected:** 1 match — only `42` at `trav_decls.cpp:11`; the rewritten operator's `0` is not spelled in source.

```text
clang-query> match integerLiteral(hasAncestor(forStmt()))
```

**Expected:** 1 match — `43` at `trav_decls.cpp:12`.

### `eachOf(Matcher<*>, ..., Matcher<*>)` — Matcher<*>

Like `anyOf`, but instead of stopping at the first alternative that
succeeds it generates **one result per matching alternative**, keeping each
alternative's bindings. With `anyOf` the same query reports `Pair` once.

```text
clang-query> match cxxRecordDecl(hasName("Pair"),
               eachOf(has(fieldDecl(hasName("first")).bind("v")),
                      has(fieldDecl(hasName("second")).bind("v"))))
```

**Expected:** 2 matches — `Pair` at `trav_decls.cpp:16` twice, `v` bound to `first` then `second`.

```text
clang-query> match cxxRecordDecl(hasName("Pair"),
               anyOf(has(fieldDecl(hasName("first")).bind("v")),
                     has(fieldDecl(hasName("second")).bind("v"))))
```

**Expected:** 1 match — `Pair` at `trav_decls.cpp:16`, `v` bound to `first`.

### `optionally(Matcher<*>)` — Matcher<*>

Always succeeds, but **keeps the inner matcher's bindings** when it does
match. Use it to collect "extra information if present" without filtering
the outer node. Both `Pair` and `Lone` match; only `Lone` gets a `var`
binding for its `other` field.

```text
clang-query> match cxxRecordDecl(anyOf(hasName("Pair"), hasName("Lone")), unless(isImplicit()),
               optionally(has(fieldDecl(hasName("other")).bind("var")))).bind("record")
```

**Expected:** 2 matches — `Pair` at `trav_decls.cpp:16` (only `record` bound) and `Lone` at `:17` (`record` and `var` bound).

### `binaryOperation(Matcher<*>...Matcher<*>)` — Matcher<*>

A single entry point for the three AST shapes a binary operator can take:
`BinaryOperator` (fundamental operands, or dependent operands in a
template), `CXXOperatorCallExpr` (overloaded operator on a class type) and
`CXXRewrittenBinaryOperator` (an inverted `==` or a `<=>` rewrite). The
inner matchers (`hasOperatorName`, `hasLHS`, `hasRHS`, …) are applied to
whichever node is present.

```text
clang-query> match binaryOperation(hasOperatorName("!="),
                                   hasLHS(expr().bind("lhs")),
                                   hasRHS(expr().bind("rhs")))
```

**Expected:** 5 matches — `1 != 2` and `Tag() != Tag()` at `trav_decls.cpp:21`, both `!=` in the template at `:22`, and the rewritten `s1 != s2` at `:24`.

Ask for the three shapes individually to see where each one came from:

```text
clang-query> match binaryOperator(hasOperatorName("!="))
```

**Expected:** 3 matches — `1 != 2` at `trav_decls.cpp:21`, and both `!=` in the template at `:22` (dependent operands stay a plain `BinaryOperator`).

```text
clang-query> match cxxOperatorCallExpr(hasOperatorName("!="))
```

**Expected:** 1 match — `Tag() != Tag()` at `trav_decls.cpp:21`.

```text
clang-query> match cxxRewrittenBinaryOperator()
```

**Expected:** 2 matches — `s1 != s2` at `trav_decls.cpp:24` (from `operator==`) and `s1 < s2` at `:26` (from `operator<=>`).

### `invocation(Matcher<*>...Matcher<*>)` — Matcher<*>

`CallExpr` and `CXXConstructExpr` share no base class, yet both have
arguments. `invocation` lets one matcher cover a call *and* a construction,
so `hasArgument(0, …)` can be written once.

```text
clang-query> match invocation(hasArgument(0, integerLiteral(equals(42))))
```

**Expected:** 2 matches — `callTakesInt(42)` at `trav_decls.cpp:31` and `ConstructorTakesInt cti(42)` at `:32`.

```text
clang-query> match callExpr(hasArgument(0, integerLiteral(equals(42))))
```

**Expected:** 1 match — only the call at `trav_decls.cpp:31`.

### `findAll(Matcher<*> Matcher)` — Matcher<*>

Matches if the node *itself* or any descendant matches, generating one
result per hit — it is defined in the C++ API as
`eachOf(M, forEachDescendant(M))`.

**Not in clang-query 22** — C++-API-only; write the expansion by hand. On `Deep` it reports the class itself plus its four nested classes:

```text
clang-query> match cxxRecordDecl(hasName("Deep"),
               eachOf(cxxRecordDecl(unless(isImplicit())).bind("m"),
                      forEachDescendant(cxxRecordDecl(unless(isImplicit())).bind("m"))))
```

**Expected:** 5 matches — `Deep` at `trav_decls.cpp:8` five times, `m` bound to `Deep`, `B`, `C`, `D`, `E`.

### `traverse(TraversalKind TK, Matcher<*> InnerMatcher)` — Matcher<*>

Runs all nested matchers with a given traversal kind, so implicit nodes
(casts, materialized temporaries, rewritten operators) are skipped inside
that subtree only.

**Not in clang-query 22** — the C++ API's per-matcher switch; in clang-query the equivalent is the session-wide `set traversal …`. The `7` in `long widened = 7;` is hidden behind an implicit cast in `AsIs` mode:

```text
clang-query> match varDecl(hasInitializer(integerLiteral()))
```

**Expected:** 2 matches — `v` at `trav_decls.cpp:11` and `v` at `:12`; `widened` is missed.

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match varDecl(hasInitializer(integerLiteral()))
```

**Expected:** 3 matches — the two `v` variables plus `widened` at `trav_decls.cpp:13`.

---

## 8.2 — Functions

These traversals start at a `FunctionDecl` (so also methods, constructors,
conversion functions and deduction guides) and step to its parameters, its
body or its `explicit` expression.

### `hasParameter(unsigned N, Matcher<ParmVarDecl>)` — Matcher<FunctionDecl>

Steps to the **N-th parameter** (zero-based) and applies the inner matcher.
Functions with fewer than N+1 parameters never match.

```text
clang-query> match functionDecl(hasParameter(0, hasType(asString("int"))))
```

**Expected:** 4 matches — `ConstructorTakesInt(int)` at `trav_decls.cpp:29`, `callTakesInt` at `:30`, `Triple::f` at `:38`, and `Expl(int)` at `:40`.

```text
clang-query> match cxxMethodDecl(hasParameter(2, hasName("z")))
```

**Expected:** 1 match — `Triple::f(int x, int y, int z)` at `trav_decls.cpp:38`.

### `hasAnyParameter(Matcher<ParmVarDecl>)` — Matcher<FunctionDecl>

Matches when **any** parameter matches; the implicit `this` is not a
parameter. Reference example: find the function that has a parameter named
`y`.

```text
clang-query> match functionDecl(hasAnyParameter(hasName("y")))
```

**Expected:** 1 match — `Triple::f` at `trav_decls.cpp:38`.

### `hasAnyBody(Matcher<Stmt>)` — Matcher<FunctionDecl>

`hasBody` (Part 9) matches only the declaration that *carries* the body.
`hasAnyBody` matches **every declaration** of a function whose body exists
somewhere in the translation unit — so the prototype of `declaredTwice` on
line 35 matches, because its definition on line 36 has a body.

```text
clang-query> match functionDecl(hasName("declaredTwice"), hasAnyBody(compoundStmt()))
```

**Expected:** 2 matches — the prototype at `trav_decls.cpp:35` and the definition at `:36`.

```text
clang-query> match functionDecl(hasName("declaredOnce"), hasAnyBody(compoundStmt()))
```

**Expected:** 0 matches — `declaredOnce` is never defined.

### `hasExplicitSpecifier(Matcher<Expr>)` — Matcher<FunctionDecl>

Steps to the expression inside `explicit(…)`, when there is one. A plain
`explicit` and a non-explicit constructor have no expression and never
match. In the `Expl` template (lines 40–44), `explicit(false)` and
`explicit(true)` carry a `ConstantExpr`; the dependent `explicit(b)` is still
a bare `DeclRefExpr` because it cannot be evaluated until instantiation.

```text
clang-query> match cxxConstructorDecl(hasExplicitSpecifier(constantExpr()))
```

**Expected:** 2 matches — `explicit(false) Expl(bool)` at `trav_decls.cpp:42` and `explicit(true) Expl(char)` at `:43`.

```text
clang-query> match cxxConstructorDecl(hasExplicitSpecifier(expr()))
```

**Expected:** 3 matches — lines `42`, `43` and the dependent `explicit(b) Expl(long)` at `trav_decls.cpp:44`.

---

## 8.3 — Methods & records

From a method you can step to its class and to the methods it overrides;
from a class you can step to its methods and to its bases, either as
`CXXBaseSpecifier` nodes (`hasAnyBase`, `hasDirectBase`) or straight to the
base's declaration (`isDerivedFrom` and friends).

### `ofClass(Matcher<CXXRecordDecl>)` — Matcher<CXXMethodDecl>

Steps from a method to the **class that declares it**. Remember that a class
owns implicit methods too (copy/move constructors, assignment), so filter
with `unless(isImplicit())` when you want only what was written.

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Dog")), unless(isImplicit()))
```

**Expected:** 1 match — `Dog::speak` at `trav_decls.cpp:49`.

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Dog")))
```

**Expected:** 4 matches — `speak` plus three implicit special members, all reported at `trav_decls.cpp:49`.

The reference's use: find the construction expression whose constructor
belongs to a given class.

```text
clang-query> match cxxConstructExpr(hasDeclaration(cxxMethodDecl(ofClass(hasName("Widget")))))
```

**Expected:** 1 match — `Widget()` at `trav_decls.cpp:55`.

### `forEachOverridden(Matcher<CXXMethodDecl>)` — Matcher<CXXMethodDecl>

Steps to each method that this method **directly overrides**, one result
per overridden method. `Puppy::speak` overrides `Dog::speak`; it reaches
`Animal::speak` only transitively, so it is not listed.

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Puppy")),
                                 forEachOverridden(cxxMethodDecl().bind("b"))).bind("d")
```

**Expected:** 1 match — `d` = `Puppy::speak` at `trav_decls.cpp:50`, `b` = `Dog::speak` at `:49`.

Multiple inheritance produces multiple results:

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Both")),
                                 forEachOverridden(cxxMethodDecl().bind("b"))).bind("d")
```

**Expected:** 2 matches — `Both::act` at `trav_decls.cpp:53` twice, `b` bound to `Left::act` (`:51`) then `Right::act` (`:52`).

### `hasMethod(Matcher<CXXMethodDecl>)` — Matcher<CXXRecordDecl>

Matches a class whose **first** method satisfying the inner matcher exists
(one result per class, like `has`).

```text
clang-query> match cxxRecordDecl(hasMethod(hasName("render")))
```

**Expected:** 1 match — `Widget` at `trav_decls.cpp:54`.

```text
clang-query> match cxxRecordDecl(hasMethod(hasName("speak")))
```

**Expected:** 3 matches — `Animal` at `trav_decls.cpp:48`, `Dog` at `:49`, `Puppy` at `:50`.

### `hasAnyBase(Matcher<CXXBaseSpecifier>)` — Matcher<CXXRecordDecl>

Matches a class with a **direct or indirect base specifier** matching. The
inner matcher sees a `CXXBaseSpecifier`, so you use `hasType(...)`,
`isPublic()`, `isVirtual()` and similar on it.

```text
clang-query> match cxxRecordDecl(hasAnyBase(hasType(cxxRecordDecl(hasName("SpecialBase")))))
```

**Expected:** 2 matches — `Proxy` at `trav_decls.cpp:57` and `IndirectlyDerived` at `:58`.

```text
clang-query> match cxxRecordDecl(hasAnyBase(isPrivate()))
```

**Expected:** 2 matches — `Proxy` at `trav_decls.cpp:57` and `IndirectlyDerived` at `:58` (a `class` base defaults to private).

### `hasDirectBase(Matcher<CXXBaseSpecifier>)` — Matcher<CXXRecordDecl>

Same, but only **direct** bases count.

```text
clang-query> match cxxRecordDecl(hasDirectBase(hasType(cxxRecordDecl(hasName("SpecialBase")))))
```

**Expected:** 1 match — `Proxy` at `trav_decls.cpp:57`; `IndirectlyDerived` is excluded.

```text
clang-query> match cxxRecordDecl(hasDirectBase(isPublic()))
```

**Expected:** 4 matches — `Dog` at `trav_decls.cpp:49`, `Puppy` at `:50`, `Both` at `:53`, `ViaTypedef` at `:61`.

### `isDerivedFrom(Matcher<NamedDecl> Base)` — Matcher<CXXRecordDecl>

The matcher-taking overload (the string form is in Part 5). Matches a class
**directly or indirectly derived** from a declaration matching `Base`; a
class is not derived from itself. Typedefs of the base are followed, which
is why the inner matcher takes a `NamedDecl` rather than a `CXXRecordDecl`.

```text
clang-query> match cxxRecordDecl(isDerivedFrom(cxxRecordDecl(hasName("Animal"))))
```

**Expected:** 2 matches — `Dog` at `trav_decls.cpp:49` and `Puppy` at `:50`.

```text
clang-query> match cxxRecordDecl(isDerivedFrom(typedefDecl()))
```

**Expected:** 1 match — `ViaTypedef` at `trav_decls.cpp:61`, whose base `SB2` is a typedef of a typedef of `SpecialBase`.

### `isDirectlyDerivedFrom(Matcher<NamedDecl> Base)` — Matcher<CXXRecordDecl>

Only **direct** derivation counts. `ViaTypedef` still matches for
`SpecialBase`, because the typedef chain resolves to that class.

```text
clang-query> match cxxRecordDecl(isDirectlyDerivedFrom(namedDecl(hasName("Animal"))))
```

**Expected:** 1 match — `Dog` at `trav_decls.cpp:49`.

```text
clang-query> match cxxRecordDecl(isDirectlyDerivedFrom(hasName("SpecialBase")))
```

**Expected:** 2 matches — `Proxy` at `trav_decls.cpp:57` and `ViaTypedef` at `:61`.

### `isSameOrDerivedFrom(Matcher<NamedDecl> Base)` — Matcher<CXXRecordDecl>

`isDerivedFrom` plus the base class itself. The base appears twice: once
as the real declaration and once as its injected class name.

```text
clang-query> match cxxRecordDecl(isSameOrDerivedFrom(hasName("SpecialBase")))
```

**Expected:** 5 matches — `SpecialBase` at `trav_decls.cpp:56` (twice: the class and its injected class name), `Proxy` at `:57`, `IndirectlyDerived` at `:58`, `ViaTypedef` at `:61`.

```text
clang-query> match cxxRecordDecl(isSameOrDerivedFrom(hasName("SpecialBase")), unless(isImplicit()))
```

**Expected:** 4 matches — the same set without the injected class name.

---

## 8.4 — Constructors

A constructor definition owns a list of `CXXCtorInitializer` nodes — the
`: hits(0), misses(0)` part. Two matchers step from the constructor into
that list, and two more step from an initializer to its field or its
expression. The sample's `Counter` is on line 64.

### `hasAnyConstructorInitializer(Matcher<CXXCtorInitializer>)` — Matcher<CXXConstructorDecl>

Matches a constructor with **at least one** initializer satisfying the
inner matcher (one result per constructor).

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(anything()))
```

**Expected:** 1 match — `Counter::Counter()` at `trav_decls.cpp:64`.

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(forField(hasName("misses"))))
```

**Expected:** 1 match — `Counter::Counter()` at `trav_decls.cpp:64`.

### `forEachConstructorInitializer(Matcher<CXXCtorInitializer>)` — Matcher<CXXConstructorDecl>

One result **per initializer** that matches (bind inside to see them).

```text
clang-query> match cxxConstructorDecl(forEachConstructorInitializer(forField(decl().bind("x"))))
```

**Expected:** 2 matches — `Counter::Counter()` at `trav_decls.cpp:64` twice, `x` bound to `hits` then `misses`.

### `forField(Matcher<FieldDecl>)` — Matcher<CXXCtorInitializer>

Steps from an initializer to the **field it initializes**. Base-class and
delegating initializers have no field and never match.

```text
clang-query> match cxxCtorInitializer(forField(hasName("hits")))
```

**Expected:** 1 match — `hits(0)` at `trav_decls.cpp:64`.

### `withInitializer(Matcher<Expr>)` — Matcher<CXXCtorInitializer>

Steps from an initializer to its **expression** (the `0` in `hits(0)`).

```text
clang-query> match cxxCtorInitializer(withInitializer(integerLiteral(equals(0))))
```

**Expected:** 2 matches — `hits(0)` and `misses(0)` at `trav_decls.cpp:64`.

---

## 8.5 — Variables, fields & bindings

Initializers of variables and fields, and the two halves of a structured
binding: the `DecompositionDecl` (`auto &[f, s, t] = arr`) and the three
`BindingDecl`s inside it (line 70).

### `hasInitializer(Matcher<Expr>)` — Matcher<VarDecl>

Steps from a variable to its **initializer expression**. Implicit casts are
part of the expression in `AsIs` mode, which is why `widened` needs
`ignoringImplicit` (or `set traversal IgnoreUnlessSpelledInSource`, see
`traverse` above).

```text
clang-query> match varDecl(hasInitializer(callExpr()))
```

**Expected:** 1 match — `bool flag = probe();` at `trav_decls.cpp:68`.

```text
clang-query> match varDecl(hasInitializer(ignoringImplicit(integerLiteral())))
```

**Expected:** 3 matches — `v` at `trav_decls.cpp:11`, `v` at `:12`, `widened` at `:13`.

### `hasInClassInitializer(Matcher<Expr>)` — Matcher<FieldDecl>

Steps from a non-static data member to its **default member initializer**
(`int a = 2;`). Fields without one never match.

```text
clang-query> match fieldDecl(hasInClassInitializer(integerLiteral(equals(2))))
```

**Expected:** 1 match — `Config::a` at `trav_decls.cpp:69`.

```text
clang-query> match fieldDecl(hasInClassInitializer(anything()))
```

**Expected:** 2 matches — `Config::a` and `Config::b` at `trav_decls.cpp:69`; `c` has no initializer.

### `hasBinding(unsigned N, Matcher<BindingDecl>)` — Matcher<DecompositionDecl>

Steps to the **N-th binding** (zero-based) of a structured binding.

```text
clang-query> match decompositionDecl(hasBinding(0, bindingDecl(hasName("f")).bind("fBinding")))
```

**Expected:** 1 match — `auto &[f, s, t]` at `trav_decls.cpp:70`, `fBinding` = `f`.

```text
clang-query> match decompositionDecl(hasBinding(2, bindingDecl(hasName("f"))))
```

**Expected:** 0 matches — binding 2 is `t`, not `f`.

### `hasAnyBinding(Matcher<BindingDecl>)` — Matcher<DecompositionDecl>

Matches when **any** binding matches, regardless of position.

```text
clang-query> match decompositionDecl(hasAnyBinding(bindingDecl(hasName("f")).bind("fBinding")))
```

**Expected:** 1 match — `auto &[f, s, t]` at `trav_decls.cpp:70`, `fBinding` = `f`.

### `forDecomposition(Matcher<ValueDecl>)` — Matcher<BindingDecl>

The reverse direction: from a **binding** up to the `DecompositionDecl` it
belongs to.

```text
clang-query> match bindingDecl(hasName("f"), forDecomposition(decompositionDecl()))
```

**Expected:** 1 match — `f` at `trav_decls.cpp:70`.

```text
clang-query> match bindingDecl(forDecomposition(
               decompositionDecl(hasInitializer(declRefExpr(to(varDecl(hasName("arr"))))))))
```

**Expected:** 3 matches — `f`, `s`, `t` at `trav_decls.cpp:70`, all bound from `arr`.

---

## 8.6 — Contexts & using

Where a declaration *lives* (its `DeclContext`), what a `using` declaration
introduces (`UsingShadowDecl`s), and what those shadows ultimately point at.

### `hasDeclContext(Matcher<Decl>)` — Matcher<Decl>

Steps from a declaration to its **enclosing declaration context** viewed as
a `Decl` — a namespace, a class, a function, or the translation unit. Only
the immediate context is checked.

```text
clang-query> match cxxRecordDecl(hasDeclContext(namedDecl(hasName("M"))))
```

**Expected:** 1 match — `N::M::D` at `trav_decls.cpp:73`.

```text
clang-query> match functionDecl(hasDeclContext(namespaceDecl(hasName("Lib"))))
```

**Expected:** 1 match — `Lib::helper` at `trav_decls.cpp:74`.

```text
clang-query> match cxxMethodDecl(hasDeclContext(cxxRecordDecl(hasName("Triple"))))
```

**Expected:** 1 match — `Triple::f` at `trav_decls.cpp:38`.

### `hasUnderlyingDecl(Matcher<NamedDecl>)` — Matcher<NamedDecl>

Steps from a named declaration to its **underlying declaration** — for a
`UsingShadowDecl` that is the thing it re-exports; for an ordinary
declaration it is the declaration itself. The reference example resolves a
dependent call `fn(T())` through the `using NF::fn;` on line 78.

```text
clang-query> match unresolvedLookupExpr(hasAnyDeclaration(
               namedDecl(hasUnderlyingDecl(hasName("::NF::fn")))))
```

**Expected:** 1 match — the `fn` in `fn(T())` at `trav_decls.cpp:78`.

```text
clang-query> match usingShadowDecl(hasUnderlyingDecl(hasName("helper")))
```

**Expected:** 1 match — the shadow introduced by `using Lib::helper;` at `trav_decls.cpp:76`.

### `hasAnyUsingShadowDecl(Matcher<UsingShadowDecl>)` — Matcher<BaseUsingDecl>

A `using X::b;` declaration owns one `UsingShadowDecl` per entity it
introduces (one per overload for functions). This matcher steps from the
`using` declaration to **any** of its shadows.

```text
clang-query> match usingDecl(hasAnyUsingShadowDecl(hasName("helper")))
```

**Expected:** 1 match — `using Lib::helper;` at `trav_decls.cpp:76`.

### `hasTargetDecl(Matcher<NamedDecl>)` — Matcher<UsingShadowDecl>

Steps from a shadow declaration to the **declaration it targets**. Combined
with `hasAnyUsingShadowDecl` this tells `using` of a function apart from
`using` of a variable.

```text
clang-query> match usingDecl(hasAnyUsingShadowDecl(hasTargetDecl(functionDecl())))
```

**Expected:** 1 match — `using Lib::helper;` at `trav_decls.cpp:76`.

```text
clang-query> match usingDecl(hasAnyUsingShadowDecl(hasTargetDecl(varDecl())))
```

**Expected:** 1 match — `using Lib::counter;` at `trav_decls.cpp:75`.

---

## 8.7 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Traversal = step + inner matcher | `ofClass`, `hasParameter`, `forField` all report the *outer* node |
| `has` vs `hasDescendant` | direct child only vs any depth; both give one result per outer node |
| `forEach…` counts | one result per matching child/descendant — but only when something is bound inside |
| Implicit nodes | `hasParent` sees implicit casts and rewritten-operator literals; `set traversal IgnoreUnlessSpelledInSource` hides them |
| Injected class name | a class "has a child" named like itself; filter with `unless(isImplicit())` |
| `hasAnyBody` vs `hasBody` | every redeclaration matches once a body exists anywhere |
| Base specifiers vs base decls | `hasAnyBase`/`hasDirectBase` see `CXXBaseSpecifier`; `isDerivedFrom(...)` sees the `NamedDecl` and follows typedefs |
| `using` plumbing | `usingDecl` → `hasAnyUsingShadowDecl` → `hasTargetDecl` / `hasUnderlyingDecl` |
| `traverse` / `findAll` | not registered; use `set traversal …` and `eachOf(m, forEachDescendant(m))` |

**Quiz.** Report every class that derives (directly or indirectly) from
`Animal` and declares a method that overrides something, binding the
overridden method as `over`. How many matches, and what does `over` bind to
in each?

> [!hint]- Hint
> Combine the matcher form of `isDerivedFrom`, `hasMethod`, and
> `forEachOverridden`. `hasMethod` stops at the first method that works, so
> each class is reported once even though `forEachOverridden` is inside.

> [!success]- Answer
> `cxxRecordDecl(isDerivedFrom(hasName("Animal")), hasMethod(forEachOverridden(cxxMethodDecl().bind("over"))))` — 2 matches: `Dog` (`over` = `Animal::speak`, line 48) and `Puppy` (`over` = `Dog::speak`, line 49).

```text
clang-query> match cxxRecordDecl(isDerivedFrom(hasName("Animal")),
                                 hasMethod(forEachOverridden(cxxMethodDecl().bind("over"))))
```

**Expected:** 2 matches — `Dog` at `trav_decls.cpp:49` and `Puppy` at `:50`.

---

[← Part 7 — Narrowing Matchers III — Types, Templates & Source Locations](part_7_narrowing_types_templates_locations.md) | [Part 9 — Traversal Matchers II — Statements & Expressions →](part_9_traversal_stmts.md)
