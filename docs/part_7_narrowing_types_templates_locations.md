# Part 7 — Narrowing Matchers III — Types, Templates & Source Locations

[← Part 6 — Narrowing Matchers II — Statements & Expressions](part_6_narrowing_stmts.md) | [Part 8 — Traversal Matchers I — Tree Navigation & Declarations →](part_8_traversal_tree_decls.md)

**Sample:** `manifests/narrow_types.cpp` · flags: `-std=c++23`

This part uses three small samples. Sections 7.1, 7.2 and 7.5 run on
`manifests/narrow_types.cpp`; section 7.3 switches to
`manifests/narrow_templates.cpp`; section 7.4 switches to
`manifests/narrow_locs.cpp`, which pulls in two headers from
`manifests/include/` and therefore needs `-isystem manifests/include`. Each
section repeats its own `**Sample:**` line so you always know which file and
flags a block runs against.

## What You'll Learn

- How type predicates (`isInteger()`, `isConstQualified()`, `voidType()`, …)
  are always reached *through* another matcher — `hasType(...)`,
  `returns(...)`, `hasAnyParameter(hasType(...))` — never on their own.
- The difference between a `QualType` (a type *plus* its `const`/`volatile`
  qualifiers) and a bare `Type`, and which predicates look at which.
- How to tell template *patterns*, *implicit instantiations* and *explicit
  specializations* apart, and how clang marks expressions inside a template as
  type-, value- or instantiation-dependent.
- The everyday noise filters — `isExpansionInMainFile()`,
  `isExpansionInSystemHeader()`, `isExpansionInFileMatching()`,
  `isExpandedFromMacro()` — and what "expansion location" means.
- How the DSL says "the same thing, twice": `equalsBoundNode("id")` and
  `declaresSameEntityAsBoundNode("id")`.

## The Big Picture

The narrowing matchers in Parts 5 and 6 asked questions about a declaration
or a statement directly. This part covers three families that sit one step
away from the node you are matching:

```text
  varDecl(hasType( ┐              functionDecl(returns( ┐
                   │  QualType /                        │  Type predicates
      isInteger()  │  Type predicates        voidType() │  (7.1, 7.2)
  ))               ┘              ))                    ┘

  cxxRecordDecl(isTemplateInstantiation())    "which copy of the template
  expr(isTypeDependent())                       am I looking at?"   (7.3)

  decl(isExpansionInMainFile())               "where was this written?"
  stmt(isExpandedFromMacro("LOG"))              — the noise filters   (7.4)

  ... .bind("v") ... equalsBoundNode("v")     "is this the node I already
                                                found?"             (7.5)
```

A few ideas hold the whole part together:

* **Types are matched through `hasType` and `returns`.** A `varDecl` node
  does not *have* the property "is an integer"; its *type* does. So you write
  `varDecl(hasType(isInteger()))`, and the predicate inside runs on a
  `QualType`. Some predicates (`booleanType()`, `voidType()`,
  `realFloatingPointType()`) are `Matcher<Type>` instead; `hasType` and
  `returns` accept both, silently dropping qualifiers for the `Type` ones.
* **`QualType` = `Type` + qualifiers.** `const int` and `int` are the same
  `Type` but different `QualType`s. `isConstQualified()` and
  `hasLocalQualifiers()` only make sense on a `QualType`; `equalsBoundNode`
  has separate overloads for each, and 7.5 shows the difference.
* **Templates produce several declarations from one piece of source.** The
  pattern (`template <typename T> class X {}`), each implicit instantiation
  (`X<A>`) and any explicit specialization (`template <> class X<int>`) are
  distinct nodes. clang-query reports instantiations *at the pattern's line*,
  so counts can look like duplicates until you dump them.
* **Source-location narrowers are your everyday filters.** Nearly every real
  query ends with `unless(isExpansionInSystemHeader())` or starts with
  `isExpansionInMainFile()`. They look at the *expansion* location — where
  the code ended up after macro expansion — not the *spelling* location
  inside the macro definition.
* **Bound-node equality is identity, not text.** `equalsBoundNode("v")`
  succeeds only when the current node is *the very same node* previously
  bound to `v`. Two `DeclRefExpr`s that both spell `x` are different nodes,
  but they refer to the same `VarDecl`, which is why the self-assignment
  idiom compares the declarations they point *to*.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/narrow_types.cpp -- -std=c++23
```

---

## 7.1 — QualType predicates

**Sample:** `manifests/narrow_types.cpp` · flags: `-std=c++23`

Everything here is a predicate on a type, wrapped by `hasType(...)` on a
declaration or expression, or by `returns(...)` on a function. The sample
declares a row of `takes_*` functions whose parameters are the interesting
types, a handful of globals with different qualifiers, and five functions
that differ only in return type. Remember that parameters are `VarDecl`s
too: a bare `varDecl(hasType(...))` will also see every parameter, so most
examples below either go through `functionDecl(hasAnyParameter(...))` or add
`hasGlobalStorage()`.

### `asString(std::string Name)` — Matcher<QualType>

Matches when the type, printed the way clang prints it, equals `Name`
exactly. That means sugar matters: a typedef prints as the typedef name, and
in C++ a class pointer prints as `Y *`, not `class Y *`. Use it when you know
the exact spelling; use the structural predicates when you do not.

```clang-query
match cxxMemberCallExpr(on(hasType(asString("Y *"))))
```

**Expected:** 1 match — the call `y->x()` at `narrow_types.cpp:28`.

The typedef `const_int` keeps its name when printed, so `asString("const int")`
does *not* find `ci`; it finds the two parameters spelled `int const` and
`const int` instead (lines 12–13):

```clang-query
match varDecl(hasType(asString("const_int")))
```

**Expected:** 1 match — `ci` at `narrow_types.cpp:18`.

### `isInteger()` — Matcher<QualType>

Matches any integer type: `int`, `unsigned long`, and also `bool`, `char`
and `wchar_t`, which are integer types in C++. Floating-point types are not.

```clang-query
match functionDecl(matchesName("takes_"),
                   hasAnyParameter(hasType(isInteger())))
```

**Expected:** 4 matches — `takes_int` (line 5), `takes_ulong` (6), `takes_char` (8), `takes_wchar` (9); `takes_double` is left out.

Through `returns(...)` the same predicate proves that `bool` counts as an
integer:

```clang-query
match functionDecl(returns(isInteger()))
```

**Expected:** 2 matches — `flag` (`bool`, line 32) and `pick` (`int`, line 60).

### `isSignedInteger()` — Matcher<QualType>

Matches signed integer types. On this target `char` and `wchar_t` are
signed, so they match as well; `unsigned long` does not.

```clang-query
match functionDecl(matchesName("takes_"),
                   hasAnyParameter(hasType(isSignedInteger())))
```

**Expected:** 3 matches — `takes_int` (line 5), `takes_char` (8), `takes_wchar` (9).

### `isUnsignedInteger()` — Matcher<QualType>

Matches unsigned integer types only.

```clang-query
match functionDecl(hasAnyParameter(hasType(isUnsignedInteger())))
```

**Expected:** 1 match — `takes_ulong(unsigned long)` at `narrow_types.cpp:6`.

### `isAnyCharacter()` — Matcher<QualType>

Matches every character type — `char`, `signed char`, `unsigned char`,
`wchar_t`, `char8_t`, `char16_t`, `char32_t` — and nothing else.

```clang-query
match functionDecl(hasAnyParameter(hasType(isAnyCharacter())))
```

**Expected:** 2 matches — `takes_char` (line 8) and `takes_wchar` (line 9).

### `isAnyPointer()` — Matcher<QualType>

Matches any pointer type, including Objective-C object pointers. Qualifiers
on the pointer or on the pointee do not matter. `hasGlobalStorage()` keeps
the local `y` in `z()` and the parameter of `ptr_to_const` out of the count.

```clang-query
match varDecl(hasType(isAnyPointer()), hasGlobalStorage())
```

**Expected:** 7 matches — `jp` (line 19), `kp` (20), `vp` (22), `ip` (24), `s` (42), `ws` (43), `w` (44).

### `isConstQualified()` — Matcher<QualType>

Matches types with a *top-level* `const`. `int const` and `const int` are
the same thing and both match; `const int *` is a non-const pointer to
const, so it does not.

```clang-query
match functionDecl(hasAnyParameter(hasType(isConstQualified())))
```

**Expected:** 2 matches — `const_param(int const)` (line 12) and `const_param2(const int)` (line 13); `ptr_to_const` is not matched.

A `const` hidden inside a typedef still counts as top-level here (compare
`hasLocalQualifiers()` below):

```clang-query
match varDecl(hasType(isConstQualified()), hasGlobalStorage())
```

**Expected:** 2 matches — `ci` (typedef `const_int`, line 18) and `jp` (`int *const`, line 19).

### `isVolatileQualified()` — Matcher<QualType>

The `volatile` twin of `isConstQualified()`: top-level `volatile` only.
`volatile int *` is a plain pointer and is not matched.

```clang-query
match varDecl(hasType(isVolatileQualified()))
```

**Expected:** 2 matches — `kp` (`int *volatile`, line 20) and `vol` (`volatile int`, line 21).

### `hasLocalQualifiers()` — Matcher<QualType>

Matches when the qualifiers are written *on this type*, not inherited from a
typedef. `ci` is `const` through `const_int`, so `isConstQualified()` sees it
but `hasLocalQualifiers()` does not.

```clang-query
match varDecl(hasType(hasLocalQualifiers()), hasGlobalStorage())
```

**Expected:** 3 matches — `jp` (line 19), `kp` (20), `vol` (21); `ci` (line 18) is excluded.

### `booleanType()` — Matcher<Type>

Matches the type `bool`. Being a `Matcher<Type>`, it ignores qualifiers.

```clang-query
match functionDecl(returns(booleanType()))
```

**Expected:** 1 match — `bool flag()` at `narrow_types.cpp:32`.

### `voidType()` — Matcher<Type>

Matches the type `void`. Most functions return `void`, so on its own this is
a very wide net; the extra terms drop the `takes_*` row (they have
parameters) and the implicit constructors of `Y`.

```clang-query
match functionDecl(returns(voidType()), parameterCountIs(0),
                   unless(isImplicit()))
```

**Expected:** 6 matches — `Y::x` declaration (line 27), `z` (28), `Y::x` definition (29), `nothing` (33), `assign_self` (52), `use_locals` (54).

### `realFloatingPointType()` — Matcher<Type>

Matches `float`, `double` and `long double`.

```clang-query
match functionDecl(returns(realFloatingPointType()))
```

**Expected:** 3 matches — `ratio` (line 34), `avg` (35), `precise` (36).

## 7.2 — Sizes: arrays and string literals

**Sample:** `manifests/narrow_types.cpp` · flags: `-std=c++23`

One matcher, two node kinds. A `ConstantArrayType` knows its element count
after constant folding, and a `StringLiteral` knows its length in
characters, *not counting* the terminating NUL.

### `hasSize(unsigned N)` — Matcher<ConstantArrayType>, Matcher<StringLiteral>

For arrays the bound is evaluated first, so `int b[2 * 21]` has size 42 just
like `int a[42]`. Types have no source location, so wrap the type matcher in
`varDecl(hasType(...))` to get lines back.

```clang-query
match varDecl(hasType(constantArrayType(hasSize(42))))
```

**Expected:** 2 matches — `a` (line 39) and `b` (line 40); `c[41]` and `d[43]` do not match.

For string literals the size is the number of characters, so `"abcd"` and
`L"abcd"` both have size 4 and `"a"` has size 1:

```clang-query
match stringLiteral(hasSize(4))
```

**Expected:** 2 matches — `"abcd"` (line 42) and `L"abcd"` (line 43).

---

## 7.3 — Templates & dependence

**Sample:** `manifests/narrow_templates.cpp` · flags: `-std=c++23`

Switch samples for this section:

```bash
$LLVM/bin/clang-query manifests/narrow_templates.cpp -- -std=c++23
```

The sample has a class template `X` with one implicit instantiation (`X<A>`)
and one explicit specialization (`X<int>`), a function template `generic`
instantiated for `unsigned` and `double` plus an explicit `int`
specialization, a variable template `zero`, two templates that are never
instantiated (`add`, `size_of`, `Derived`, `Importer`) so their bodies stay
*dependent*, and `Count<42>` for integral template arguments.

```text
  template <typename T> class X {};      pattern      (never "instantiated")
  X<A> xa;                               X<A>         isTemplateInstantiation
  template <> class X<int> {};           X<int>       isExplicitTemplateSpecialization
```

### `isTemplateInstantiation()` — Matcher<CXXRecordDecl>, Matcher<FunctionDecl>, Matcher<VarDecl>

Matches the *instantiations* a template produced — implicit ones like
`X<A>` and explicit instantiations (`template class X<A>;`) — but neither
the pattern nor an explicit specialization. clang-query reports each
instantiation at the pattern's line, because that is where its source is.

```clang-query
match cxxRecordDecl(hasName("X"), isTemplateInstantiation())
```

**Expected:** 1 match — `X<A>`, reported at the pattern on `narrow_templates.cpp:7`; `X<int>` is a specialization and is skipped.

```clang-query
match functionDecl(isTemplateInstantiation())
```

**Expected:** 2 matches — `generic<unsigned>` and `generic<double>`, both reported at line 14.

```clang-query
match varDecl(isTemplateInstantiation())
```

**Expected:** 2 matches — both are the single node `zero<int>` (line 19), which clang-query visits twice: once under the variable template and once as a top-level declaration. `set output dump` shows the same address for both.

### `isExplicitTemplateSpecialization()` — Matcher<CXXRecordDecl>, Matcher<FunctionDecl>, Matcher<VarDecl>

The complement: `template <> …` declarations the programmer wrote by hand.

```clang-query
match cxxRecordDecl(isExplicitTemplateSpecialization())
```

**Expected:** 1 match — `template <> class X<int>` at `narrow_templates.cpp:10`.

```clang-query
match functionDecl(isExplicitTemplateSpecialization())
```

**Expected:** 1 match — `template <> void generic(int n)` at `narrow_templates.cpp:15`.

```clang-query
match varDecl(isExplicitTemplateSpecialization())
```

**Expected:** 1 match — `template <> char zero<char>` at `narrow_templates.cpp:20`.

### `isInstantiated()` — Matcher<Decl>

Matches declarations that *are* instantiations or live *inside* one. It is
wider than `isTemplateInstantiation()`: the implicit constructors that
`X<A>` and `Count<42>` receive are instantiated too (without
`unless(isImplicit())` the count is 8).

```clang-query
match functionDecl(isInstantiated(), unless(isImplicit()))
```

**Expected:** 2 matches — `generic<unsigned>` and `generic<double>` at line 14.

### `isInTemplateInstantiation()` — Matcher<Stmt>

The statement-side twin: matches statements whose enclosing declaration is
an instantiation. The dependent `T i = t;` only exists once per
instantiation, so it is matched twice.

```clang-query
match declStmt(isInTemplateInstantiation())
```

**Expected:** 2 matches — `T i = t;` in `generic<unsigned>` and in `generic<double>`, both at line 14.

The non-dependent `m += 1;` is *not* excluded by `unless(...)`: clang treats
it as belonging to the instantiations as well as the pattern, exactly as the
reference warns.

```clang-query
match binaryOperator(hasOperatorName("+="),
                     unless(isInTemplateInstantiation()))
```

**Expected:** 0 matches — every copy of `m += 1;` counts as inside an instantiation.

### `isTypeDependent()` — Matcher<Expr>

Inside a template that has not been instantiated, an expression whose type
depends on a template parameter is *type-dependent*: `x + y` in `add`
(because `x` is a `T`) and `T() + T()`; `y` on its own is a plain `int`.

```clang-query
match binaryOperator(isTypeDependent())
```

**Expected:** 2 matches — `x + y` (line 25) and `T() + T()` (line 26).

### `isValueDependent()` — Matcher<Expr>

An expression is *value-dependent* when its value depends on a template
parameter. Every type-dependent expression is also value-dependent, so the
`unless` isolates the interesting case: the reference to the non-type
parameter `Size`, whose type is known (`int`) but whose value is not.

```clang-query
match declRefExpr(isValueDependent(), unless(isTypeDependent()))
```

**Expected:** 1 match — `Size` in `return Size;` at `narrow_templates.cpp:28`.

The inner `sizeof(T() + T())` is value-dependent too: its type is `size_t`,
but its value depends on `T`.

```clang-query
match unaryExprOrTypeTraitExpr(isValueDependent())
```

**Expected:** 1 match — the inner `sizeof(T() + T())` at line 26.

### `isInstantiationDependent()` — Matcher<Expr>

The weakest form of dependence: the expression *mentions* a template
parameter even though both its type and its value are already known. The
outer `sizeof(sizeof(…))` is the textbook case — the size of a `size_t` does
not depend on `T`, but `T` appears inside.

```clang-query
match unaryExprOrTypeTraitExpr(isInstantiationDependent(),
                               unless(isValueDependent()))
```

**Expected:** 1 match — the outer `sizeof(sizeof(T() + T()))` at `narrow_templates.cpp:26`.

### `hasDependentName(std::string N)` — Matcher<DependentNameType>, Matcher<DependentScopeDeclRefExpr>

When a name is looked up through a template parameter (`T::v`,
`typename T::type`) clang cannot resolve it yet and records only the name.
`hasDependentName` matches on that recorded name.

```clang-query
match dependentScopeDeclRefExpr(hasDependentName("v"))
```

**Expected:** 1 match — `T::v` in `Derived::f` at `narrow_templates.cpp:30`.

Types have no location, so the `DependentNameType` overload is best reached
from the typedef that uses it:

```clang-query
match typedefDecl(hasType(dependentNameType(hasDependentName("type"))))
```

**Expected:** 1 match — `typedef typename T::type dependent_name` at `narrow_templates.cpp:31`.

### `templateArgumentCountIs(unsigned N)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<FunctionDecl>, Matcher<TemplateSpecializationType>, Matcher<VarTemplateSpecializationDecl>

Matches a specialization (or a written template type) with exactly `N`
template arguments. Every specialization counts, implicit or explicit.

```clang-query
match classTemplateSpecializationDecl(templateArgumentCountIs(1))
```

**Expected:** 3 matches — `X<A>` (reported at line 7), `X<int>` (line 10), `Count<42>` (reported at line 34).

```clang-query
match functionDecl(templateArgumentCountIs(1))
```

**Expected:** 3 matches — `generic<unsigned>` and `generic<double>` (line 14) and the explicit `generic<int>` (line 15).

The `TemplateSpecializationType` overload looks at the type *as written* in
a declaration:

```clang-query
match varDecl(hasType(templateSpecializationType(templateArgumentCountIs(1))))
```

**Expected:** 3 matches — `xa` (line 9), `xi` (line 11), `c42` (line 35).

The `VarTemplateSpecializationDecl` overload exists in the library, but
clang-query 22 registers no `varTemplateSpecializationDecl()` node matcher
and `varDecl(...)` refuses the argument type, so it cannot be reached from
the DSL; use `varDecl(isTemplateInstantiation())` or
`varDecl(isExplicitTemplateSpecialization())` from above instead.

### `templateArgumentLocCountIs(unsigned MatchCount)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<DeclRefExpr>, Matcher<FunctionDecl>, Matcher<OverloadExpr>, Matcher<TemplateSpecializationTypeLoc>, Matcher<VarTemplateSpecializationDecl>

Counts *written* template arguments (`TemplateArgumentLoc`s) rather than
the resolved ones, so `A<int> a` has one even when defaults fill in more.

**Not in clang-query 22** — trunk-only; the matcher is newer than this build. The nearest working alternative counts the resolved arguments through the type instead:

```clang-query
match varDecl(hasType(templateSpecializationType(templateArgumentCountIs(1))))
```

**Expected:** 3 matches — `xa` (line 9), `xi` (line 11), `c42` (line 35).

### `equalsIntegralValue(std::string Value)` — Matcher<TemplateArgument>

Matches an integral template argument with exactly this value. The value is
passed as a string because template arguments are arbitrary-precision; use
the canonical base-10 spelling.

```clang-query
match classTemplateSpecializationDecl(
  hasAnyTemplateArgument(equalsIntegralValue("42")))
```

**Expected:** 1 match — `Count<42>`, reported at the pattern on `narrow_templates.cpp:34`.

### `isIntegral()` — Matcher<TemplateArgument>

Matches any template argument that is an integral value (as opposed to a
type, a template, or a pack). `X<A>` has a type argument and is skipped.

```clang-query
match classTemplateSpecializationDecl(hasAnyTemplateArgument(isIntegral()))
```

**Expected:** 1 match — `Count<42>`, reported at line 34.

---

## 7.4 — Source locations & macros

**Sample:** `manifests/narrow_locs.cpp` · flags: `-std=c++23 -isystem manifests/include`

Switch samples again; this one needs the extra include flag:

```bash
$LLVM/bin/clang-query manifests/narrow_locs.cpp -- -std=c++23 -isystem manifests/include
```

`narrow_locs.cpp` includes `<sys.h>` (found through `-isystem`, so clang
treats it as a *system header*) and `"include/helpers.h"` (a normal project
header), defines three macros, and uses all of them:

```text
  manifests/narrow_locs.cpp        main file      Local, hits, twice, run
  manifests/include/sys.h          system header  SysBuffer, log_line, sys_clamp
  manifests/include/helpers.h      user header    Helper, helper_count, helper_twice
```

Every node carries a source location, and after macro expansion each
location has two views. The **spelling** location is where the characters
were typed — for `((x) * (x))` that is line 6, inside `#define SQUARE`. The
**expansion** location is where the macro was *used* — line 13 for
`SQUARE(n)`. All four matchers in this section reason about the expansion
location, which is what you want: "is this in my file?" should say yes for
`hits`, even though its declaration was typed inside `DECLARE_COUNTER`.

### `isExpansionInMainFile()` — Matcher<Decl>, Matcher<Stmt>, Matcher<TypeLoc>

Matches nodes whose expansion location is in the main file — the file you
passed on the command line — and nothing from any header. `class Local`
has an implicit injected-class-name inside it, hence `unless(isImplicit())`.

```clang-query
match cxxRecordDecl(isExpansionInMainFile(), unless(isImplicit()))
```

**Expected:** 1 match — `Local` at `narrow_locs.cpp:10`; `SysBuffer` and `Helper` live in headers.

The variable `hits` was produced by `DECLARE_COUNTER(hits)`; its expansion
location is line 11 of the main file, so it is matched (the other hit is the
parameter `n` of `twice`):

```clang-query
match varDecl(isExpansionInMainFile())
```

**Expected:** 2 matches — `hits` (line 11, from the macro) and the parameter `n` (line 13).

```clang-query
match returnStmt(isExpansionInMainFile())
```

**Expected:** 1 match — `return SQUARE(n);` at `narrow_locs.cpp:13`; the returns in the headers are out.

### `isExpansionInSystemHeader()` — Matcher<Decl>, Matcher<Stmt>, Matcher<TypeLoc>

Matches nodes that come from a system header — anything found through
`-isystem`, the compiler's builtin include directories, or a
`#pragma clang system_header`. `sys.h` qualifies; `helpers.h` does not.

```clang-query
match functionDecl(isExpansionInSystemHeader())
```

**Expected:** 2 matches — `log_line` (`sys.h:4`) and `sys_clamp` (`sys.h:5`).

```clang-query
match returnStmt(isExpansionInSystemHeader())
```

**Expected:** 1 match — the `return` inside `sys_clamp` at `sys.h:5`.

The `TypeLoc` overload works the same way; `loc(asString(...))` picks one
written type so the count stays readable:

```clang-query
match typeLoc(loc(asString("const char *")), isExpansionInSystemHeader())
```

**Expected:** 1 match — the `const char *` of `log_line`'s parameter at `sys.h:4`.

In practice you will use it negated far more often than positively — this
is the everyday "ignore the standard library" filter:

```clang-query
match cxxRecordDecl(unless(isImplicit()), unless(isExpansionInSystemHeader()))
```

**Expected:** 2 matches — `Helper` (`helpers.h:3`) and `Local` (`narrow_locs.cpp:10`); `SysBuffer` is filtered out.

### `isExpansionInFileMatching(StringRef RegExp, Regex::RegexFlags Flags = NoFlags)` — Matcher<Decl>, Matcher<Stmt>, Matcher<TypeLoc>

Matches nodes whose expansion file name contains a match for the regex
(unanchored, so `"helpers"` finds `…/include/helpers.h`). The optional
second argument is the flags string — `"IgnoreCase"`, `"BasicRegex"`, or
both joined with `|`.

```clang-query
match varDecl(isExpansionInFileMatching("helpers"))
```

**Expected:** 2 matches — `helper_count` (`helpers.h:4`) and the parameter `n` of `helper_twice` (`helpers.h:5`).

Without `"IgnoreCase"` the upper-case pattern matches nothing; with it, both
functions in the header are found:

```clang-query
match functionDecl(isExpansionInFileMatching("HELPERS", "IgnoreCase"))
```

**Expected:** 2 matches — `Helper::assist` (`helpers.h:3`) and `helper_twice` (`helpers.h:5`).

```clang-query
match returnStmt(isExpansionInFileMatching("helpers.h"))
```

**Expected:** 1 match — `return n * 2;` in `helper_twice` at `helpers.h:5`.

### `isExpandedFromMacro(std::string MacroName)` — Matcher<Decl>, Matcher<Stmt>, Matcher<TypeLoc>

Matches nodes that were produced, in full, by an expansion of the named
macro (directly or through another macro). If only *part* of the node came
from the macro — `SQUARE(hits) + 1`, where the `+ 1` is ordinary source —
it does not match.

```clang-query
match varDecl(isExpandedFromMacro("DECLARE_COUNTER"))
```

**Expected:** 1 match — `hits`, expanded from `DECLARE_COUNTER(hits)` at `narrow_locs.cpp:11`.

```clang-query
match binaryOperator(isExpandedFromMacro("SQUARE"))
```

**Expected:** 2 matches — the `(n) * (n)` inside `twice` (line 13) and `(hits) * (hits)` inside `run` (line 17).

The `+` on line 17 wraps a macro expansion but is not itself from the macro:

```clang-query
match binaryOperator(hasOperatorName("+"), isExpandedFromMacro("SQUARE"))
```

**Expected:** 0 matches — `SQUARE(hits) + 1` is only partly macro-generated.

```clang-query
match callExpr(isExpandedFromMacro("LOG"))
```

**Expected:** 1 match — the `log_line("start")` call produced by `LOG("start")` at `narrow_locs.cpp:16`.

The `TypeLoc` overload finds the written `int` of `hits`, which also came
out of the macro:

```clang-query
match typeLoc(isExpandedFromMacro("DECLARE_COUNTER"))
```

**Expected:** 1 match — the `int` type of `hits` at `narrow_locs.cpp:11`.

---

## 7.5 — Bound-node equality

**Sample:** `manifests/narrow_types.cpp` · flags: `-std=c++23`

Back to the first sample:

```bash
$LLVM/bin/clang-query manifests/narrow_types.cpp -- -std=c++23
```

`.bind("id")` stores a node while a match is being evaluated. The two
matchers here read that store back: `equalsBoundNode("id")` asks "is the
current node *identical* to what I bound?", and
`declaresSameEntityAsBoundNode("id")` relaxes that to "does it declare the
same entity?" — which is what you need when a function is declared once and
defined elsewhere, as two different `Decl` nodes. Because bindings only live
inside one match, the bound node and the comparison must sit in the *same*
matcher expression, and the `.bind` must be evaluated first (matchers run
left to right).

```text
  self = self          binaryOperator
                       ├─ LHS: DeclRefExpr ──to──▶ VarDecl self   .bind("v")
                       └─ RHS: DeclRefExpr ──to──▶ VarDecl self   equalsBoundNode("v")  ✓
  m = self             ├─ LHS: ──to──▶ VarDecl m      .bind("v")
                       └─ RHS: ──to──▶ VarDecl self   equalsBoundNode("v")  ✗
```

### `equalsBoundNode(std::string ID)` — Matcher<Decl>, Matcher<QualType>, Matcher<Stmt>, Matcher<Type>

Matches when the current node is the same node previously bound to `ID`.
The `Decl` overload gives the classic self-assignment finder: two different
`DeclRefExpr`s that both point `to` the same `VarDecl`. In the default
`AsIs` traversal the right-hand side sits under an implicit lvalue-to-rvalue
cast, hence `ignoringImpCasts`.

```clang-query
match binaryOperator(hasOperatorName("="),
  hasLHS(declRefExpr(to(varDecl().bind("v")))),
  hasRHS(ignoringImpCasts(declRefExpr(to(varDecl(equalsBoundNode("v")))))))
```

**Expected:** 1 match — `self = self` at `narrow_types.cpp:52`; `m = self` on the same line and `m = v` in `use_locals` fail the equality.

Combined with `forEachDescendant`, `equalsBoundNode` acts as a *filter*: the
first `forEachDescendant` tries every local variable in turn, the second
keeps only references to that particular variable, and the match is reported
once per (variable, use) pair:

```clang-query
match compoundStmt(
  forEachDescendant(varDecl().bind("d")),
  forEachDescendant(declRefExpr(to(decl(equalsBoundNode("d"))))))
```

**Expected:** 4 matches — the body of `z` twice (`obj` used in `&obj`, `y` used in `y->x()`, line 28) and the body of `use_locals` twice (`u` on line 56, `v` on line 57).

The `QualType` overload compares a type *with* its qualifiers. Binding the
first field's type and demanding that a different field has the very same
`QualType` finds `Pair` (two `int`s) but not `Qual` (`int` vs `const int`)
or `Mixed` (`int` vs `double`):

```clang-query
match cxxRecordDecl(
  has(fieldDecl(hasType(qualType().bind("q"))).bind("f1")),
  has(fieldDecl(unless(equalsBoundNode("f1")),
                hasType(qualType(equalsBoundNode("q"))))))
```

**Expected:** 1 match — `Pair` at `narrow_types.cpp:47`.

The `Type` overload drops the qualifiers, so `int` and `const int` now
compare equal and `Qual` joins the result:

```clang-query
match cxxRecordDecl(
  has(fieldDecl(hasType(type().bind("t"))).bind("f1")),
  has(fieldDecl(unless(equalsBoundNode("f1")),
                hasType(type(equalsBoundNode("t"))))))
```

**Expected:** 2 matches — `Pair` (line 47) and `Qual` (line 49); `Mixed` (line 48) still differs.

The `Stmt` overload is pure node identity, useful for proving that two
traversal paths reached the same node. `hasReturnValue` and `has` both lead
to the conditional expression in `pick`:

```clang-query
match returnStmt(hasReturnValue(expr().bind("r")),
                 has(expr(equalsBoundNode("r"))))
```

**Expected:** 1 match — the `return lhs == rhs ? lhs : rhs;` at `narrow_types.cpp:60`.

Identity is not spelling: the two operands of `lhs == rhs` are different
nodes, so comparing them as statements never succeeds — you have to go
through `to(...)` and compare declarations, as in the first example.

```clang-query
match binaryOperator(hasOperatorName("=="),
                     hasLHS(expr().bind("l")),
                     hasRHS(expr(equalsBoundNode("l"))))
```

**Expected:** 0 matches — distinct `DeclRefExpr` nodes are never equal as statements.

### `declaresSameEntityAsBoundNode(std::string ID)` — Matcher<Decl>

Matches a declaration that declares the same entity as the node bound to
`ID`, even when it is a different `Decl` node — a prototype and its
out-of-line definition, or the member declaration `void x();` inside `Y`
and `void Y::x() {}` outside it. Both `forEachDescendant`s hang off the
translation unit so that the prototype is bound before the definition is
tested.

```clang-query
match translationUnitDecl(
  forEachDescendant(functionDecl(unless(isDefinition())).bind("proto")),
  forEachDescendant(functionDecl(isDefinition(),
                                 declaresSameEntityAsBoundNode("proto"))))
```

**Expected:** 1 match — the pair `Y::x` declared at `narrow_types.cpp:27` and defined at line 29; the other prototypes (`takes_*`, `flag`, …) have no definition.

### `equalsNode(const Decl* Other)` — Matcher<Decl>, Matcher<Stmt>, Matcher<Type>

Matches when the node is pointer-identical to a node you already hold — a
`Decl*`, `Stmt*` or `Type*` you obtained in C++ code.

**Not in clang-query 22** — C++-API-only: its argument is a raw AST pointer, which the DSL has no way to spell. The equivalent from the DSL is to bind the node first and use `equalsBoundNode`:

```clang-query
match returnStmt(hasReturnValue(expr().bind("r")),
                 has(expr(equalsBoundNode("r"))))
```

**Expected:** 1 match — the return statement of `pick` at `narrow_types.cpp:60`.

## 7.6 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Type predicates are reached through `hasType`/`returns` | `functionDecl(returns(booleanType()))` found `flag`; `varDecl(hasType(isAnyPointer()))` found the seven pointer globals |
| `QualType` vs `Type` | `isConstQualified()` saw the typedef'd `const`; `hasLocalQualifiers()` did not; `equalsBoundNode` on `qualType` found `Pair` only, on `type` found `Pair` and `Qual` |
| `asString` compares spelling | `"Y *"` matched, `"class Y *"` would not; `const_int` printed as its typedef name |
| Instantiation vs specialization | `isTemplateInstantiation()` found `X<A>`, `isExplicitTemplateSpecialization()` found `X<int>`; both are reported at the pattern's line |
| Three kinds of dependence | `x + y` type-dependent, `Size` value-dependent only, outer `sizeof` instantiation-dependent only |
| Expansion location | `hits` from `DECLARE_COUNTER` counted as main-file; `SQUARE(hits) + 1` was *not* "expanded from" `SQUARE` |
| System header vs project header | `-isystem` made `sys.h` invisible to `unless(isExpansionInSystemHeader())` while `helpers.h` stayed |
| Bound-node identity | `self = self` matched through `to(varDecl(equalsBoundNode("v")))`; `lhs == rhs` did not match as statements |

**Quiz.** Using `manifests/narrow_types.cpp`, find every *global* variable
whose type is a pointer **and** carries a local `const` or `volatile`
qualifier on the pointer itself — but not the plain `int *ip` or the
`const char *` strings.

> [!hint]- Hint
> Three narrowing predicates from 7.1 combine inside one `hasType(...)`:
> the pointer test, the local-qualifier test, and `hasGlobalStorage()` on
> the `varDecl` to skip parameters and locals. `const char *` has its
> `const` on the pointee, not on the pointer, so `hasLocalQualifiers()`
> already rejects it.

> [!success]- Answer
> `varDecl(hasGlobalStorage(), hasType(isAnyPointer()), hasType(hasLocalQualifiers()))` — 2 matches: `jp` (`int *const`, line 19) and `kp` (`int *volatile`, line 20).

---

[← Part 6 — Narrowing Matchers II — Statements & Expressions](part_6_narrowing_stmts.md) | [Part 8 — Traversal Matchers I — Tree Navigation & Declarations →](part_8_traversal_tree_decls.md)
