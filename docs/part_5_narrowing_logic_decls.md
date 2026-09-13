# Part 5 — Narrowing Matchers I — Logic & Declarations

[← Part 4 — Node Matchers III — Types & TypeLocs](part_4_node_matchers_types.md) | [Part 6 — Narrowing Matchers II — Statements & Expressions →](part_6_narrowing_stmts.md)

**Sample:** `manifests/narrow_decls.cpp` · flags: `-std=c++23`

## What You'll Learn
- What a *narrowing* matcher is and why its return type tells you which node matcher accepts it.
- The five logical combinators: `allOf` (implicit in every argument list), `anyOf`, `unless`, `anything`, and `mapAnyOf`.
- Matching declarations by name, qualified name, regex and linkage.
- Filtering by access, namespace, attribute, storage, and every `is…()` property of functions, methods, constructors, records, variables, fields and parameters.
- Why so many results are *implicit* nodes the compiler added, and how `unless(isImplicit())` hides them.

## The Big Picture

Part 2–4 gave you **node matchers** — they pick a *kind* of node
(`functionDecl()`, `cxxRecordDecl()`, `varDecl()`). A **narrowing
matcher** never picks a node; it is a *predicate on the node you are
already standing on*. It goes inside a node matcher's parentheses and
answers yes/no:

```text
   functionDecl(  isDefinition(),  parameterCountIs(3)  )
   └── node ──┘  └───────── narrowing predicates ──────┘
                   (an implicit allOf: every one must hold)
```

Every narrowing matcher in the reference has a **return type** —
`Matcher<FunctionDecl>`, `Matcher<CXXMethodDecl>`, `Matcher<Decl>`, … That
column is the whole contract: the predicate fits inside any node matcher
whose node type *is or derives from* that type.

```text
   Decl ─┬─ NamedDecl ─┬─ ValueDecl ─┬─ DeclaratorDecl ─┬─ FunctionDecl ─ CXXMethodDecl ─ CXXConstructorDecl
         │             │             │                  ├─ VarDecl ─ ParmVarDecl
         │             │             │                  └─ FieldDecl
         │             ├─ TagDecl ─┬─ RecordDecl ─ CXXRecordDecl
         │             │           └─ EnumDecl
         │             └─ NamespaceDecl
         └─ (isImplicit, isPublic, hasAttr … work on ALL of these: Matcher<Decl>)
```

So `isConst()` (Matcher<CXXMethodDecl>) is legal inside `cxxMethodDecl()`
and `cxxConstructorDecl()` but is rejected inside `functionDecl()` —
clang-query prints an "Incorrect type for arg" error. Conversely
`hasName()` (Matcher<NamedDecl>) works nearly everywhere.

Some names are **overloaded**: `isImplicit()` exists for `Attr`, `Decl`,
`InitListExpr` and `LambdaCapture`; `isConstexpr()` for `FunctionDecl`,
`IfStmt` and `VarDecl`. One spelling, several predicates — clang-query
picks the overload from the enclosing node matcher.

One recurring surprise: the AST is full of nodes you never typed —
injected-class-names, implicit constructors, closure classes, implicit
`operator new`. They match too. You will use `unless(isImplicit())` a lot
in this part; section 5.9 explains exactly what it hides.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/narrow_decls.cpp -- -std=c++23
```

---

## 5.1 — Logical combinators

These five are the glue of the DSL. They are `Matcher<*>`: they take any
matchers and return a matcher of the same node type, so they fit anywhere.

### `allOf(Matcher<*>, ..., Matcher<*>)` — Matcher<*>

Matches when *every* inner matcher matches. You rarely write it, because
the argument list of any node matcher is already an implicit `allOf`. The
explicit form is useful when a matcher takes exactly one argument (like
`hasAnyConstructorInitializer`) and you need to combine several predicates.

```text
clang-query> match functionDecl(allOf(isDefinition(), parameterCountIs(3)))
```

**Expected:** 1 match — `three` at `narrow_decls.cpp:78` (the only function with three parameters *and* a body).

The same thing without the `allOf`:

```text
clang-query> match functionDecl(isDefinition(), parameterCountIs(3))
```

**Expected:** 1 match — the same `three` at `narrow_decls.cpp:78`.

### `anyOf(Matcher<*>, ..., Matcher<*>)` — Matcher<*>

Matches when *at least one* inner matcher matches. It is the only way to
say "or".

```text
clang-query> match cxxRecordDecl(anyOf(hasName("Dog"), hasName("Mammal")),
                                 unless(isImplicit()))
```

**Expected:** 2 matches — `Mammal` at `narrow_decls.cpp:134` and `Dog` at `narrow_decls.cpp:135`.

Drop the `unless(isImplicit())` and the count doubles: every class
definition also contains an implicit *injected-class-name* (`Dog::Dog` the
type, not a constructor), and it carries the same name.

```text
clang-query> match cxxRecordDecl(anyOf(hasName("Dog"), hasName("Mammal")))
```

**Expected:** 4 matches — each of `narrow_decls.cpp:134` and `:135` twice (the definition and its injected-class-name).

### `anything()` — Matcher<*>

Matches any node. It is a placeholder for a slot that *requires* a
matcher when you have no further constraint — "does this parameter have
an initializer at all?"

```text
clang-query> match parmVarDecl(hasInitializer(anything()))
```

**Expected:** 1 match — `mode` at `narrow_decls.cpp:168` (`int mode = 0`, the only parameter with a default argument).

### `mapAnyOf(nodeMatcherFunction...)` — Matcher<*> (reference: Matcher<unspecified>)

Applies the same inner matchers to *several node kinds* at once. Write the
node matcher **names** without parentheses, then chain `.with(...)` for
the inner matchers; they are combined as-if with `allOf` inside each node
matcher. `mapAnyOf(ifStmt, forStmt).with(X)` is exactly
`anyOf(ifStmt(X), forStmt(X))`, but you type `X` once.

```text
clang-query> match mapAnyOf(ifStmt, forStmt).with(
                 hasCondition(cxxBoolLiteral(equals(true))))
```

**Expected:** 2 matches — `if (true)` at `narrow_decls.cpp:173` and `for (; true;)` at `narrow_decls.cpp:174` (the `while (true)` on line 175 is not in the list).

### `unless(Matcher<*>)` — Matcher<*>

Negation: matches when the inner matcher does *not* match. Combined with
`isImplicit()` it is the most typed matcher in this lab.

```text
clang-query> match enumDecl(unless(isScoped()))
```

**Expected:** 1 match — the unscoped `enum Color` at `narrow_decls.cpp:137` (`enum class Level` is excluded).

---

## 5.2 — Names and linkage

All four return `Matcher<NamedDecl>`, so they work inside any node matcher
for a declaration that has a name — functions, variables, classes,
namespaces, fields, enumerators, …

### `hasName(StringRef Name)` — Matcher<NamedDecl>

Matches a declaration whose name is `Name`. The name may be qualified with
enclosing namespaces or classes; a qualified name matches as a *suffix* of
the fully qualified name, and a leading `::` anchors it at the global
namespace. Typedef names of the underlying type do not count. The sample
has three classes called `Circle`: `::Circle`, `geo::Circle` and
`geo::shapes::Circle`.

```text
clang-query> match cxxRecordDecl(hasName("Circle"), unless(isImplicit()))
```

**Expected:** 3 matches — `narrow_decls.cpp:7`, `:10` and `:12`.

```text
clang-query> match cxxRecordDecl(hasName("shapes::Circle"), unless(isImplicit()))
```

**Expected:** 1 match — `geo::shapes::Circle` at `narrow_decls.cpp:7`.

```text
clang-query> match cxxRecordDecl(hasName("geo::Circle"), unless(isImplicit()))
```

**Expected:** 1 match — `geo::Circle` at `narrow_decls.cpp:10` (the suffix `geo::Circle` does not match `geo::shapes::Circle`; qualifiers must line up).

```text
clang-query> match cxxRecordDecl(hasName("::Circle"), unless(isImplicit()))
```

**Expected:** 1 match — the global `Circle` at `narrow_decls.cpp:12`.

### `hasAnyName(StringRef, ..., StringRef)` — Matcher<NamedDecl>

Matches if the name is any of the given names. It is a faster spelling of
`anyOf(hasName(a), hasName(b), …)`; every argument accepts the same
qualified forms as `hasName`.

```text
clang-query> match cxxRecordDecl(hasAnyName("Dog", "Mammal", "Animal"),
                                 unless(isImplicit()))
```

**Expected:** 3 matches — `Animal`, `Mammal`, `Dog` at `narrow_decls.cpp:133`–`135`.

### `matchesName(StringRef RegExp, Regex::RegexFlags Flags = NoFlags)` — Matcher<NamedDecl>

Matches when the regular expression finds a match *anywhere* in the
**fully qualified** name (`::geo::shapes::Circle`). Anchor with `^` and
`$` when you mean the whole name. In clang-query the optional flags are a
quoted string such as `"IgnoreCase"`; combine with `|`, e.g.
`"IgnoreCase | BasicRegex"`.

```text
clang-query> match namedDecl(matchesName("^::geo::.*Circle$"), unless(isImplicit()))
```

**Expected:** 2 matches — `geo::shapes::Circle` at `narrow_decls.cpp:7` and `geo::Circle` at `narrow_decls.cpp:10`.

```text
clang-query> match namedDecl(matchesName("circle$", "IgnoreCase"), unless(isImplicit()))
```

**Expected:** 3 matches — all three `Circle` classes (`narrow_decls.cpp:7`, `:10`, `:12`).

### `hasExternalFormalLinkage()` — Matcher<NamedDecl>

Matches a declaration with external *formal* linkage — the linkage the
language assigns, before the compiler decides what it can hide. A plain
namespace-scope `int` has it; a `static` one does not; locals never do.

```text
clang-query> match varDecl(hasExternalFormalLinkage(),
                           hasAnyName("global_counter", "file_counter", "g_plain", "g_static"))
```

**Expected:** 2 matches — `global_counter` at `narrow_decls.cpp:14` and `g_plain` at `narrow_decls.cpp:142` (the two `static` variables are internal).

For functions, note that `helper` inside the anonymous namespace is
treated as *internal* linkage by clang 22 and does not match:

```text
clang-query> match functionDecl(hasExternalFormalLinkage(),
                                hasAnyName("helper", "file_local", "defined"))
```

**Expected:** 1 match — `defined` at `narrow_decls.cpp:60`.

---

## 5.3 — Access, namespaces and attributes

Access specifiers apply to two very different nodes: a member declaration
(`Matcher<Decl>`) and a base-class specifier (`Matcher<CXXBaseSpecifier>`).
The base overload is reached through `hasDirectBase(...)` / `hasAnyBase(...)`
on a `cxxRecordDecl`. Namespace predicates are on `Matcher<Decl>` (is this
declaration *inside* such a namespace?) or `Matcher<NamespaceDecl>` (is
this namespace itself anonymous/inline?). For `isInline()` on namespaces
see its shared entry in 5.4.

### `isPublic()` — Matcher<CXXBaseSpecifier>, Matcher<Decl>

On a declaration: it is in a `public:` section (or in a `struct`, where
that is the default). On a base specifier: the inheritance is public.

```text
clang-query> match fieldDecl(isPublic(), hasAnyName("id", "balance", "pin"))
```

**Expected:** 1 match — `Account::id` at `narrow_decls.cpp:24`.

```text
clang-query> match cxxRecordDecl(hasDirectBase(isPublic()))
```

**Expected:** 7 matches — `PublicChild` (`:32`), `VirtualChild` (`:35`), `Rect` (`:93`), `Sealed` (`:97`), `Point3D` (`:123`), `Mammal` (`:134`), `Dog` (`:135`) — every `struct X : Base` is public by default.

### `isProtected()` — Matcher<CXXBaseSpecifier>, Matcher<Decl>

Protected member, or protected inheritance.

```text
clang-query> match fieldDecl(isProtected())
```

**Expected:** 1 match — `Account::balance` at `narrow_decls.cpp:26`.

```text
clang-query> match cxxRecordDecl(hasDirectBase(isProtected()))
```

**Expected:** 1 match — `ProtectedChild` at `narrow_decls.cpp:33`.

### `isPrivate()` — Matcher<CXXBaseSpecifier>, Matcher<Decl>

Private member, or private inheritance — including the *default*
inheritance of a `class`.

```text
clang-query> match fieldDecl(isPrivate(), hasAnyName("id", "balance", "pin"))
```

**Expected:** 1 match — `Account::pin` at `narrow_decls.cpp:28`.

Without the name filter you get three more: a lambda's captures become
*private fields* of its closure class.

```text
clang-query> match fieldDecl(isPrivate())
```

**Expected:** 4 matches — `pin` (`:28`), the init-capture field at `narrow_decls.cpp:158`, and the two capture fields of the lambda at `narrow_decls.cpp:186`.

```text
clang-query> match cxxRecordDecl(hasDirectBase(isPrivate()))
```

**Expected:** 1 match — `class PrivateChild : Base` at `narrow_decls.cpp:34`.

### `isInStdNamespace()` — Matcher<Decl>

The declaration lives directly in namespace `std` — inline namespaces
inside `std` (like libc++'s `__1`) count, but nested named namespaces
such as `std::experimental` do not.

```text
clang-query> match cxxRecordDecl(hasName("vector"), isInStdNamespace(), unless(isImplicit()))
```

**Expected:** 1 match — `std::__1::vector` at `narrow_decls.cpp:39` (`std::__1::experimental::vector` on line 41 is excluded).

### `isInAnonymousNamespace()` — Matcher<Decl>

The declaration is inside an anonymous namespace at any depth.

```text
clang-query> match namedDecl(isInAnonymousNamespace(), unless(isImplicit()))
```

**Expected:** 2 matches — `helper` at `narrow_decls.cpp:18` and the anonymous-namespace `Widget` at `narrow_decls.cpp:51`.

### `isAnonymous()` — Matcher<NamespaceDecl>

The namespace declaration *itself* is `namespace { … }`.

```text
clang-query> match namespaceDecl(isAnonymous())
```

**Expected:** 2 matches — `narrow_decls.cpp:17` and `narrow_decls.cpp:50`.

### `hasAttr(attr::Kind AttrKind)` — Matcher<Decl>

The declaration carries an attribute of the given kind. In clang-query the
kind is a quoted string with the `attr::` prefix, using Clang's internal
attribute class name — `[[deprecated]]` is `attr::Deprecated`,
`[[noreturn]]` is `attr::CXX11NoReturn`, `override`/`final` are
`attr::Override`/`attr::Final`.

```text
clang-query> match decl(hasAttr("attr::Deprecated"))
```

**Expected:** 1 match — `old_api` at `narrow_decls.cpp:55`.

```text
clang-query> match decl(hasAttr("attr::Final"))
```

**Expected:** 2 matches — `Rect::draw` at `narrow_decls.cpp:95` and `struct Sealed final` at `narrow_decls.cpp:97`.

```text
clang-query> match decl(hasAttr("attr::CXX11NoReturn"))
```

**Expected:** 1 match — `die` at `narrow_decls.cpp:67` (`"attr::NoReturn"` is the GNU `__attribute__((noreturn))` spelling and matches nothing here).

---

## 5.4 — Functions

`Matcher<FunctionDecl>` predicates fit inside `functionDecl()` and all of
its descendants (`cxxMethodDecl`, `cxxConstructorDecl`, …). Several are
shared with `VarDecl` or `FunctionProtoType`; the type overloads are
reached with `hasType(functionProtoType(...))`.

### `isDefinition()` — Matcher<FunctionDecl>, Matcher<TagDecl>, Matcher<VarDecl>

The declaration is the one that *defines* the entity: a function with a
body, a class with a body, a variable that is not `extern`.

```text
clang-query> match functionDecl(hasAnyName("declared_only", "defined"), isDefinition())
```

**Expected:** 1 match — `defined` at `narrow_decls.cpp:60`.

```text
clang-query> match tagDecl(hasAnyName("Defined", "Forward"), isDefinition())
```

**Expected:** 1 match — `class Defined {}` at `narrow_decls.cpp:131`.

```text
clang-query> match varDecl(hasAnyName("g_plain", "g_extern"), isDefinition())
```

**Expected:** 1 match — `g_plain` at `narrow_decls.cpp:142`.

### `isInline()` — Matcher<FunctionDecl>, Matcher<NamespaceDecl>, Matcher<VarDecl>

The `inline` keyword was written. Members defined in-class are inline by
rule but not by keyword, so they do not match; lambda call operators and
compiler-generated members are marked inline internally, which is why the
example excludes methods.

```text
clang-query> match functionDecl(isInline(), unless(cxxMethodDecl()))
```

**Expected:** 1 match — `inlined` at `narrow_decls.cpp:61`.

```text
clang-query> match namespaceDecl(isInline())
```

**Expected:** 2 matches — `std::__1` at `narrow_decls.cpp:38` and `outer::v2` at `narrow_decls.cpp:47`.

```text
clang-query> match varDecl(isInline())
```

**Expected:** 1 match — `g_inline` at `narrow_decls.cpp:148`.

### `isConstexpr()` — Matcher<FunctionDecl>, Matcher<IfStmt>, Matcher<VarDecl>

A `constexpr` function or variable, or an `if constexpr`. A `consteval`
function counts as constexpr too.

```text
clang-query> match functionDecl(isConstexpr(), unless(cxxMethodDecl()))
```

**Expected:** 2 matches — `square` at `narrow_decls.cpp:62` and `cube` at `narrow_decls.cpp:63`.

```text
clang-query> match varDecl(isConstexpr())
```

**Expected:** 1 match — `g_constexpr` at `narrow_decls.cpp:147`.

```text
clang-query> match ifStmt(isConstexpr())
```

**Expected:** 1 match — `if constexpr (sizeof(int) == 4)` at `narrow_decls.cpp:176`.

### `isConsteval()` — Matcher<FunctionDecl>, Matcher<IfStmt>

A `consteval` function, or an `if consteval` / `if ! consteval`.

```text
clang-query> match functionDecl(isConsteval())
```

**Expected:** 1 match — `cube` at `narrow_decls.cpp:63`.

```text
clang-query> match ifStmt(isConsteval())
```

**Expected:** 1 match — `if consteval {}` at `narrow_decls.cpp:177`.

### `isDefaulted()` — Matcher<FunctionDecl>

The function is `= default`. Compiler-generated special members are
"defaulted" too, so filter them out to see only what was written.

```text
clang-query> match functionDecl(isDefaulted(), unless(isImplicit()))
```

**Expected:** 1 match — `virtual ~Shape() = default` at `narrow_decls.cpp:84`.

```text
clang-query> match functionDecl(isDefaulted())
```

**Expected:** 28 matches — the same `~Shape` plus 27 implicit constructors, destructors and assignment operators.

### `isDeleted()` — Matcher<FunctionDecl>

The function is `= delete`. Again the compiler deletes members on its own
(e.g. the copy constructor of a class with a user-declared move
assignment), so `unless(isImplicit())` matters.

```text
clang-query> match functionDecl(isDeleted(), unless(isImplicit()))
```

**Expected:** 1 match — `erased` at `narrow_decls.cpp:64`.

### `isExternC()` — Matcher<FunctionDecl>, Matcher<VarDecl>

Declared with C language linkage, either `extern "C" void f()` or inside
an `extern "C" { … }` block.

```text
clang-query> match functionDecl(isExternC())
```

**Expected:** 2 matches — `c_entry` at `narrow_decls.cpp:65` and `c_other` at `narrow_decls.cpp:66`.

```text
clang-query> match varDecl(isExternC())
```

**Expected:** 1 match — `g_cvar` at `narrow_decls.cpp:149`.

### `isMain()` — Matcher<FunctionDecl>

The program entry point.

```text
clang-query> match functionDecl(isMain())
```

**Expected:** 1 match — `main` at `narrow_decls.cpp:80`.

### `isNoReturn()` — Matcher<FunctionDecl>

The function has a noreturn attribute of any spelling (`[[noreturn]]`,
`__attribute__((noreturn))`, `_Noreturn`).

```text
clang-query> match functionDecl(isNoReturn())
```

**Expected:** 1 match — `die` at `narrow_decls.cpp:67`.

### `isNoThrow()` — Matcher<FunctionDecl>, Matcher<FunctionProtoType>

The exception specification promises not to throw: `noexcept`,
`noexcept(true)`, or the old `throw()`. Plain functions and
`noexcept(false)` do not match. Many implicit members are noexcept, hence
the name filter.

```text
clang-query> match functionDecl(isNoThrow(),
                 hasAnyName("may_throw", "no_throw", "no_throw_true", "old_style", "may_throw_false"))
```

**Expected:** 3 matches — `no_throw` (`:69`), `no_throw_true` (`:70`) and `old_style` (`:71`).

The type overload, reached through the function's `FunctionProtoType`:

```text
clang-query> match functionDecl(hasName("no_throw"), hasType(functionProtoType(isNoThrow())))
```

**Expected:** 1 match — `no_throw` at `narrow_decls.cpp:69`.

### `hasDynamicExceptionSpec()` — Matcher<FunctionDecl>, Matcher<FunctionProtoType>

A *dynamic* exception specification — the `throw(...)` family. Since
C++17 only the empty `throw()` still parses (it means `noexcept`), and it
is the only one in the sample.

```text
clang-query> match functionDecl(hasDynamicExceptionSpec())
```

**Expected:** 1 match — `old_style() throw()` at `narrow_decls.cpp:71`.

```text
clang-query> match functionDecl(hasName("old_style"), hasType(functionProtoType(hasDynamicExceptionSpec())))
```

**Expected:** 1 match — the same `old_style` at `narrow_decls.cpp:71`.

### `isStaticStorageClass()` — Matcher<FunctionDecl>, Matcher<VarDecl>

The `static` keyword was written as a storage class — file-local
functions, file-local globals, and static locals. (Not to be confused
with static *members*.)

```text
clang-query> match functionDecl(isStaticStorageClass(), unless(isImplicit()))
```

**Expected:** 1 match — `file_local` at `narrow_decls.cpp:73`.

```text
clang-query> match varDecl(isStaticStorageClass())
```

**Expected:** 3 matches — `file_counter` (`:15`), `g_static` (`:143`) and `local_static` (`:153`).

### `isVariadic()` — Matcher<FunctionDecl>

A C-style variadic function (`...`). Parameter packs are not variadic in
this sense.

```text
clang-query> match functionDecl(isVariadic())
```

**Expected:** 1 match — `printf_like` at `narrow_decls.cpp:74`.

### `isWeak()` — Matcher<FunctionDecl>

The function is a weak symbol (`__attribute__((weak))` or `weakref`).

```text
clang-query> match functionDecl(isWeak())
```

**Expected:** 1 match — `weak_symbol` at `narrow_decls.cpp:75`.

### `parameterCountIs(unsigned N)` — Matcher<FunctionDecl>, Matcher<FunctionProtoType>

Exactly `N` parameters (the variadic `...` is not counted; a C++23
explicit object parameter `this T self` *is*).

```text
clang-query> match functionDecl(parameterCountIs(2), hasAnyName("one", "two", "three"))
```

**Expected:** 1 match — `two` at `narrow_decls.cpp:77`.

```text
clang-query> match functionDecl(hasName("three"), hasType(functionProtoType(parameterCountIs(3))))
```

**Expected:** 1 match — `three` at `narrow_decls.cpp:78`.

### `hasTrailingReturn()` — Matcher<FunctionDecl>

Declared with a trailing return type, `auto f() -> int`. Deduction guides
and lambda call operators are built with trailing return types
internally, so they are excluded here.

```text
clang-query> match functionDecl(hasTrailingReturn(), unless(cxxMethodDecl()),
                                unless(cxxDeductionGuideDecl()))
```

**Expected:** 1 match — `trailing` at `narrow_decls.cpp:79`.

---

## 5.5 — Methods

`Matcher<CXXMethodDecl>` predicates go inside `cxxMethodDecl()`,
`cxxConstructorDecl()`, `cxxDestructorDecl()` and `cxxConversionDecl()`.
The sample's `Shape` / `Rect` / `Sealed` hierarchy on lines 83–97 drives
this section.

### `isConst()` — Matcher<CXXMethodDecl>

A `const`-qualified member function. Lambda call operators are `const` by
default, so the example restricts to one class.

```text
clang-query> match cxxMethodDecl(isConst(), ofClass(hasName("Shape")))
```

**Expected:** 2 matches — `Shape::area` at `narrow_decls.cpp:85` and `Shape::name` at `narrow_decls.cpp:87`.

### `isVirtual()` — Matcher<CXXBaseSpecifier>, Matcher<CXXMethodDecl>

On a method: it is virtual, whether the keyword was written or it
inherited virtuality from an overridden method. On a base specifier:
`virtual` inheritance.

```text
clang-query> match cxxMethodDecl(isVirtual(), unless(isImplicit()))
```

**Expected:** 5 matches — `~Shape` (`:84`), `Shape::area` (`:85`), `Shape::draw` (`:86`), `Rect::area` (`:94`), `Rect::draw` (`:95`).

```text
clang-query> match cxxRecordDecl(hasDirectBase(isVirtual()))
```

**Expected:** 1 match — `VirtualChild : virtual Base` at `narrow_decls.cpp:35`.

### `isVirtualAsWritten()` — Matcher<CXXMethodDecl>

The `virtual` keyword itself was written. `Rect::area` is virtual but was
declared with `override` only, so it drops out.

```text
clang-query> match cxxMethodDecl(isVirtualAsWritten())
```

**Expected:** 3 matches — `~Shape`, `Shape::area`, `Shape::draw` at `narrow_decls.cpp:84`–`86`.

### `isPure()` — Matcher<CXXMethodDecl>

A pure virtual method (`= 0`).

```text
clang-query> match cxxMethodDecl(isPure())
```

**Expected:** 1 match — `Shape::area` at `narrow_decls.cpp:85`.

### `isOverride()` — Matcher<CXXMethodDecl>

The method overrides a base-class method — regardless of whether the
`override` keyword was used. Implicit destructors of derived classes
override too, so they are excluded.

```text
clang-query> match cxxMethodDecl(isOverride(), unless(isImplicit()))
```

**Expected:** 2 matches — `Rect::area` at `narrow_decls.cpp:94` and `Rect::draw` at `narrow_decls.cpp:95`.

### `isFinal()` — Matcher<CXXMethodDecl>, Matcher<CXXRecordDecl>

The method or class is marked `final`.

```text
clang-query> match cxxMethodDecl(isFinal())
```

**Expected:** 1 match — `Rect::draw` at `narrow_decls.cpp:95`.

```text
clang-query> match cxxRecordDecl(isFinal())
```

**Expected:** 1 match — `struct Sealed final` at `narrow_decls.cpp:97`.

### `isUserProvided()` — Matcher<CXXMethodDecl>

The method was written by the user *and* not defaulted or deleted on its
first declaration. `~Shape() = default` is user-*declared* but not
user-*provided*.

```text
clang-query> match cxxMethodDecl(isUserProvided(), ofClass(hasName("Shape")))
```

**Expected:** 7 matches — every `Shape` member from `area` (`:85`) to `scale` (`:91`), but not `~Shape`.

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Shape")), unless(isUserProvided()))
```

**Expected:** 2 matches — the defaulted `~Shape` at `narrow_decls.cpp:84` and one implicit member.

### `isCopyAssignmentOperator()` — Matcher<CXXMethodDecl>

An `operator=` taking `const T&` (or `T&`, `volatile` variants). Every
class that needs one gets an implicit copy assignment, so filter.

```text
clang-query> match cxxMethodDecl(isCopyAssignmentOperator(), unless(isImplicit()))
```

**Expected:** 1 match — `Shape::operator=(const Shape&)` at `narrow_decls.cpp:89`.

### `isMoveAssignmentOperator()` — Matcher<CXXMethodDecl>

An `operator=` taking `T&&`.

```text
clang-query> match cxxMethodDecl(isMoveAssignmentOperator(), unless(isImplicit()))
```

**Expected:** 1 match — `Shape::operator=(Shape&&)` at `narrow_decls.cpp:90`.

### `isExplicitObjectMemberFunction()` — Matcher<CXXMethodDecl>

A C++23 "deducing this" member function — its first parameter is written
`this T self`.

```text
clang-query> match cxxMethodDecl(isExplicitObjectMemberFunction())
```

**Expected:** 1 match — `Shape::scale(this Shape& self, int k)` at `narrow_decls.cpp:91`.

---

## 5.6 — Constructors, conversions and initializers

Constructor predicates return `Matcher<CXXConstructorDecl>`; `isExplicit`
is shared with conversion functions and deduction guides. The
`CXXCtorInitializer` predicates describe one entry of a
member-initializer list and are reached via
`hasAnyConstructorInitializer(...)`. `struct Point` (lines 100–113) and
`Point3D` (lines 123–128) are the playground.

### `isDefaultConstructor()` — Matcher<CXXConstructorDecl>

A constructor callable with no arguments. Note that a redeclaration
(the out-of-line definition `Point::Point()`) is a second match.

```text
clang-query> match cxxConstructorDecl(isDefaultConstructor())
```

**Expected:** 3 matches — `Point()` at `narrow_decls.cpp:102`, its definition at `narrow_decls.cpp:113`, and `Point3D()` at `narrow_decls.cpp:125`.

### `isCopyConstructor()` — Matcher<CXXConstructorDecl>

A constructor taking `const T&` (or `T&`).

```text
clang-query> match cxxConstructorDecl(isCopyConstructor(), unless(isImplicit()))
```

**Expected:** 1 match — `Point(const Point&)` at `narrow_decls.cpp:103`.

```text
clang-query> match cxxConstructorDecl(isCopyConstructor())
```

**Expected:** 5 matches — the same plus four implicit copy constructors (`Shape`, `Rect`, `Sealed`, `Point3D`).

### `isMoveConstructor()` — Matcher<CXXConstructorDecl>

A constructor taking `T&&`.

```text
clang-query> match cxxConstructorDecl(isMoveConstructor(), unless(isImplicit()))
```

**Expected:** 1 match — `Point(Point&&)` at `narrow_decls.cpp:104`.

### `isDelegatingConstructor()` — Matcher<CXXConstructorDecl>

The constructor's initializer list calls another constructor of the same
class (`: Point(...)`).

```text
clang-query> match cxxConstructorDecl(isDelegatingConstructor())
```

**Expected:** 2 matches — `Point(double)` at `narrow_decls.cpp:107` and `Point::Point()` at `narrow_decls.cpp:113`.

### `isExplicit()` — Matcher<CXXConstructorDecl>, Matcher<CXXConversionDecl>, Matcher<CXXDeductionGuideDecl>

The `explicit` specifier is present *and resolves to true*:
`explicit(false)` does not match, `explicit(true)` does, and a dependent
`explicit(b)` is not resolved.

```text
clang-query> match cxxConstructorDecl(isExplicit())
```

**Expected:** 2 matches — `explicit Point(int)` at `narrow_decls.cpp:105` and `explicit(true) Point(char)` at `narrow_decls.cpp:109`.

```text
clang-query> match cxxConversionDecl(isExplicit())
```

**Expected:** 1 match — `explicit operator bool()` at `narrow_decls.cpp:111`.

```text
clang-query> match cxxDeductionGuideDecl(isExplicit())
```

**Expected:** 1 match — `explicit Box(double) -> Box<double>` at `narrow_decls.cpp:121`.

### `isInheritingConstructor()` — Matcher<CXXConstructorDecl>

Matches a constructor that a class inherits through `using Base::Base;`.

**Not in clang-query 22** — the reference lists it but this build's
dynamic registry does not register it (`Matcher not found`). The nearest
working alternative is to find the `using` declaration whose shadow
declarations target constructors:

```text
clang-query> match usingDecl(hasAnyUsingShadowDecl(hasTargetDecl(cxxConstructorDecl())))
```

**Expected:** 1 match — `using Point::Point;` at `narrow_decls.cpp:127`.

### `isBaseInitializer()` — Matcher<CXXCtorInitializer>

The initializer initializes a base class. The compiler adds an implicit
base initializer when none is written, so `Point3D(int)` matches as well.

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(isBaseInitializer()))
```

**Expected:** 2 matches — `Point3D()` at `narrow_decls.cpp:125` and `Point3D(int)` at `narrow_decls.cpp:126`.

### `isMemberInitializer()` — Matcher<CXXCtorInitializer>

The initializer initializes a non-static data member.

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(isMemberInitializer()),
                                      unless(isImplicit()))
```

**Expected:** 3 matches — `Point(int, int)` (`:106`), `Point3D()` (`:125`), `Point3D(int)` (`:126`).

### `isWritten()` — Matcher<CXXCtorInitializer>

The initializer appears in the source, as opposed to being added by the
compiler. Combine it with `isBaseInitializer()` (inside an explicit
`allOf`, since `hasAnyConstructorInitializer` takes one matcher) to keep
only the base initializer someone typed.

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(
                 allOf(isBaseInitializer(), isWritten())))
```

**Expected:** 1 match — `Point3D() : Point(), z(0)` at `narrow_decls.cpp:125`.

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(isWritten()))
```

**Expected:** 5 matches — `narrow_decls.cpp:106`, `:107`, `:113`, `:125`, `:126` (delegating initializers count as written).

---

## 5.7 — Records and tags

`TagDecl` covers `struct`, `class`, `union` and `enum`; `CXXRecordDecl`
predicates add inheritance and lambda tests. The string overloads of the
`isDerivedFrom` family are shortcuts for `isDerivedFrom(hasName("…"))`
(the matcher overloads live in Part 10).

### `hasDefinition()` — Matcher<CXXRecordDecl>

The class has a definition somewhere in the translation unit.

```text
clang-query> match cxxRecordDecl(hasAnyName("Defined", "Forward"), hasDefinition())
```

**Expected:** 1 match — `class Defined {}` at `narrow_decls.cpp:131` (`class Forward;` has none).

### `isDerivedFrom(std::string BaseName)` — Matcher<CXXRecordDecl>

The class derives — directly or indirectly — from a class named
`BaseName`.

```text
clang-query> match cxxRecordDecl(isDerivedFrom("Animal"), unless(isImplicit()))
```

**Expected:** 2 matches — `Mammal` at `narrow_decls.cpp:134` and `Dog` at `narrow_decls.cpp:135`.

### `isDirectlyDerivedFrom(std::string BaseName)` — Matcher<CXXRecordDecl>

Only *direct* bases count.

```text
clang-query> match cxxRecordDecl(isDirectlyDerivedFrom("Animal"), unless(isImplicit()))
```

**Expected:** 1 match — `Mammal` at `narrow_decls.cpp:134`.

### `isSameOrDerivedFrom(std::string BaseName)` — Matcher<CXXRecordDecl>

Like `isDerivedFrom` but the named class itself matches too.

```text
clang-query> match cxxRecordDecl(isSameOrDerivedFrom("Animal"), unless(isImplicit()))
```

**Expected:** 3 matches — `Animal`, `Mammal`, `Dog` at `narrow_decls.cpp:133`–`135`.

### `isLambda()` — Matcher<CXXRecordDecl>

The implicit closure class generated for a lambda expression. Its location
is the lambda's `[`.

```text
clang-query> match cxxRecordDecl(isLambda())
```

**Expected:** 3 matches — the closures at `narrow_decls.cpp:139`, `:158` and `:186`.

### `isClass()` — Matcher<TagDecl>

Spelled with the `class` keyword. The next four entries use the same five
tags — `Defined`, `Animal`, `Number`, `Color`, `Level` — so you can see
each keyword pick its own.

```text
clang-query> match tagDecl(isClass(), hasAnyName("Defined", "Animal", "Number", "Color", "Level"),
                           unless(isImplicit()))
```

**Expected:** 1 match — `class Defined` at `narrow_decls.cpp:131`.

### `isStruct()` — Matcher<TagDecl>

Spelled with `struct`.

```text
clang-query> match tagDecl(isStruct(), hasAnyName("Defined", "Animal", "Number", "Color", "Level"),
                           unless(isImplicit()))
```

**Expected:** 1 match — `struct Animal` at `narrow_decls.cpp:133`.

### `isUnion()` — Matcher<TagDecl>

Spelled with `union`.

```text
clang-query> match tagDecl(isUnion(), hasAnyName("Defined", "Animal", "Number", "Color", "Level"),
                           unless(isImplicit()))
```

**Expected:** 1 match — `union Number` at `narrow_decls.cpp:136`.

### `isEnum()` — Matcher<TagDecl>

Spelled with `enum` — scoped or not.

```text
clang-query> match tagDecl(isEnum(), hasAnyName("Defined", "Animal", "Number", "Color", "Level"),
                           unless(isImplicit()))
```

**Expected:** 2 matches — `enum Color` at `narrow_decls.cpp:137` and `enum class Level` at `narrow_decls.cpp:138`.

### `isScoped()` — Matcher<EnumDecl>

A C++11 scoped enumeration (`enum class` / `enum struct`).

```text
clang-query> match enumDecl(isScoped())
```

**Expected:** 1 match — `enum class Level` at `narrow_decls.cpp:138`.

---

## 5.8 — Variables, fields and parameters

The storage family answers "where does this variable live?" A `let`
binding keeps the eight-name filter short: the sample's `storage_demo`
(lines 151–159) holds a local, a static local, a thread-local local and a
catch parameter; lines 142–149 hold the globals.

### `hasAutomaticStorageDuration()` — Matcher<VarDecl>

Lives on the stack: ordinary locals, parameters, and catch variables.

```text
clang-query> let storage hasAnyName("local", "caught", "local_static", "local_thread",
                                    "g_plain", "g_static", "g_extern", "g_thread")
clang-query> match varDecl(hasAutomaticStorageDuration(), storage)
```

**Expected:** 2 matches — `local` at `narrow_decls.cpp:152` and `caught` at `narrow_decls.cpp:156`.

### `hasLocalStorage()` — Matcher<VarDecl>

Function scope *and* non-static — for C++ this is the same set as
automatic storage.

```text
clang-query> let storage hasAnyName("local", "caught", "local_static", "local_thread",
                                    "g_plain", "g_static", "g_extern", "g_thread")
clang-query> match varDecl(hasLocalStorage(), storage)
```

**Expected:** 2 matches — `local` (`:152`) and `caught` (`:156`).

### `hasGlobalStorage()` — Matcher<VarDecl>

Everything that does *not* have local storage: namespace-scope variables,
static locals, thread-locals.

```text
clang-query> let storage hasAnyName("local", "caught", "local_static", "local_thread",
                                    "g_plain", "g_static", "g_extern", "g_thread")
clang-query> match varDecl(hasGlobalStorage(), storage)
```

**Expected:** 6 matches — `g_plain`, `g_static`, `g_extern`, `g_thread` (`:142`–`145`), `local_static` (`:153`), `local_thread` (`:154`).

### `hasStaticStorageDuration()` — Matcher<VarDecl>

Lives for the whole program: namespace-scope variables (including
`static` and `extern` ones) and static locals — but not thread-locals.

```text
clang-query> let storage hasAnyName("local", "caught", "local_static", "local_thread",
                                    "g_plain", "g_static", "g_extern", "g_thread")
clang-query> match varDecl(hasStaticStorageDuration(), storage)
```

**Expected:** 4 matches — `g_plain` (`:142`), `g_static` (`:143`), `g_extern` (`:144`), `local_static` (`:153`).

### `hasThreadStorageDuration()` — Matcher<VarDecl>

Declared `thread_local`, at any scope.

```text
clang-query> let storage hasAnyName("local", "caught", "local_static", "local_thread",
                                    "g_plain", "g_static", "g_extern", "g_thread")
clang-query> match varDecl(hasThreadStorageDuration(), storage)
```

**Expected:** 2 matches — `g_thread` at `narrow_decls.cpp:145` and `local_thread` at `narrow_decls.cpp:154`.

### `isStaticLocal()` — Matcher<VarDecl>

A local variable with static storage — `static` *or* `thread_local`
inside a function.

```text
clang-query> match varDecl(isStaticLocal())
```

**Expected:** 2 matches — `local_static` at `narrow_decls.cpp:153` and `local_thread` at `narrow_decls.cpp:154`.

### `isConstinit()` — Matcher<VarDecl>

Declared with the C++20 `constinit` specifier (a `constexpr` variable does
not count).

```text
clang-query> match varDecl(isConstinit())
```

**Expected:** 1 match — `g_constinit` at `narrow_decls.cpp:146`.

### `isExceptionVariable()` — Matcher<VarDecl>

The variable declared by a `catch (T x)` clause.

```text
clang-query> match varDecl(isExceptionVariable())
```

**Expected:** 1 match — `caught` at `narrow_decls.cpp:156`.

### `isInitCapture()` — Matcher<VarDecl>

The implicit variable behind a lambda init-capture `[x = expr]`.

```text
clang-query> match varDecl(isInitCapture())
```

**Expected:** 1 match — `captured` at `narrow_decls.cpp:158`.

### `isBitField()` — Matcher<FieldDecl>

A non-static data member declared with a bit width.

```text
clang-query> match fieldDecl(isBitField())
```

**Expected:** 3 matches — `Flags::a`, `b`, `c` at `narrow_decls.cpp:162`–`164`.

### `hasBitWidth(unsigned Width)` — Matcher<FieldDecl>

A bit-field of exactly `Width` bits.

```text
clang-query> match fieldDecl(hasBitWidth(2))
```

**Expected:** 2 matches — `a` at `narrow_decls.cpp:162` and `c` at `narrow_decls.cpp:164`.

### `hasDefaultArgument()` — Matcher<ParmVarDecl>

The parameter has a default argument. The reference marks it deprecated in
favour of `hasInitializer(...)`, which also lets you match the default's
value (see `anything()` in 5.1).

```text
clang-query> match parmVarDecl(hasDefaultArgument())
```

**Expected:** 1 match — `mode` at `narrow_decls.cpp:168`.

### `isAtPosition(unsigned N)` — Matcher<ParmVarDecl>

The parameter is the `N`-th (zero-based) in its function's list. Two extra
hits come from the implicit `operator new(size_t, std::align_val_t)`
declarations clang adds for the polymorphic `Shape`; the ancestor test
drops them.

```text
clang-query> match parmVarDecl(isAtPosition(2), unless(hasAncestor(decl(isImplicit()))))
```

**Expected:** 2 matches — `c` of `three` at `narrow_decls.cpp:78` and `third` of `positional` at `narrow_decls.cpp:169`.

```text
clang-query> match parmVarDecl(isAtPosition(2))
```

**Expected:** 4 matches — the two above plus two parameters of implicit `operator new` declarations (no source location).

---

## 5.9 — Implicit nodes

### `isImplicit()` — Matcher<Attr>, Matcher<Decl>, Matcher<InitListExpr>, Matcher<LambdaCapture>

The node was added by the compiler rather than written by you. Four
overloads share the name; the enclosing node matcher selects one.

**Decl.** Injected-class-names, closure classes, implicit special members,
implicit `operator new`/`delete`. This sample has 31 implicit record
declarations alone:

```text
clang-query> match cxxRecordDecl(isImplicit())
```

**Expected:** 31 matches — one injected-class-name per class definition, plus the three lambda closure types.

An alternative to `unless(isImplicit())` is switching traversal mode,
which hides implicit nodes globally:

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match cxxRecordDecl(hasName("Circle"))
```

**Expected:** 3 matches — `narrow_decls.cpp:7`, `:10`, `:12`; the injected-class-names are gone.

**Attr.** Implicit attributes are rare in user code; here they all hang
off the implicit `operator new` / `operator delete` declarations
(`VisibilityAttr`, `ReturnsNonNullAttr`, `AllocSizeAttr`, …). The
non-implicit ones are exactly the seven you can see in the source.

```text
clang-query> match attr(unless(isImplicit()))
```

**Expected:** 7 matches — `[[deprecated]]` (`:55`), `[[noreturn]]` (`:67`), `weak` (`:75`), `override` (`:94`), `final` (`:95`, `:97`), `constinit` (`:146`).

```text
clang-query> match attr(isImplicit())
```

**Expected:** 23 matches — all without a source location.

**LambdaCapture.** In `[&, j]`, the capture of `i` is implicit (it came
from the `&` default) while `j` is explicit.

```text
clang-query> match lambdaExpr(hasAnyCapture(lambdaCapture(isImplicit())))
```

**Expected:** 1 match — the lambda at `narrow_decls.cpp:186`.

```text
clang-query> match lambdaExpr(hasAnyCapture(lambdaCapture(unless(isImplicit()))))
```

**Expected:** 2 matches — `narrow_decls.cpp:158` (init-capture) and `narrow_decls.cpp:186` (the explicit `j`).

**InitListExpr.** The reference lists this overload, but clang-query 22
rejects `initListExpr(isImplicit())` with "Incorrect type for arg 1 …
Actual = Matcher<Decl|Attr|LambdaCapture>" — the dynamic registry only
knows the other three. The implicit inner list that `nested = {}` gets for
its `Inner` member is still reachable structurally:

```text
clang-query> match varDecl(hasName("nested"), hasInitializer(initListExpr(has(initListExpr()))))
```

**Expected:** 1 match — `nested` at `narrow_decls.cpp:182` (the outer `{}` contains a compiler-added `{}` for `inner`).

---

## 5.10 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Narrowing = predicate | `isDefinition()`, `parameterCountIs(3)` sit *inside* `functionDecl()` and only say yes/no |
| Return type = where it fits | `isConst()` needs `cxxMethodDecl()`; `hasName()` fits any `namedDecl()` |
| Implicit `allOf` | Every argument list is an AND; `allOf` is only needed inside single-argument slots |
| `anyOf` / `unless` / `anything` | OR, NOT, and "any value here" |
| `mapAnyOf(...).with(...)` | One inner matcher applied to several node kinds |
| Qualified names | `hasName("geo::Circle")` is a suffix match; `::` anchors at global scope |
| Access on two node kinds | `isPrivate()` on a field vs. on a base specifier via `hasDirectBase` |
| `hasAttr("attr::…")` | Attribute kinds use Clang's internal class names |
| Overloads | `isConstexpr` for functions, variables and `if constexpr`; `isExplicit` for ctors, conversions, guides |
| Ctor-initializers | `hasAnyConstructorInitializer` + `isBaseInitializer` / `isMemberInitializer` / `isWritten` |
| Storage family | automatic / local / global / static / thread — five overlapping sets |
| `isImplicit()` | Four overloads; `InitListExpr` and `isInheritingConstructor` are not in clang-query 22 |

**Quiz.** Find every constructor a human wrote in the sample that takes
exactly one parameter and is neither a copy nor a move constructor. How
many are there?

> [!hint]- Hint
> Start from `cxxConstructorDecl(...)`. You need three narrowing predicates:
> one to drop compiler-generated constructors, one for the parameter count,
> and one `unless(anyOf(...))` for the two special kinds.

> [!success]- Answer
> `cxxConstructorDecl(unless(isImplicit()), parameterCountIs(1), unless(anyOf(isCopyConstructor(), isMoveConstructor())))` — 6 matches: `Point(int)` (`:105`), `Point(double)` (`:107`), `Point(bool)` (`:108`), `Point(char)` (`:109`), `Box(T v)` (`:118`), `Point3D(int)` (`:126`).

---

[← Part 4 — Node Matchers III — Types & TypeLocs](part_4_node_matchers_types.md) | [Part 6 — Narrowing Matchers II — Statements & Expressions →](part_6_narrowing_stmts.md)
