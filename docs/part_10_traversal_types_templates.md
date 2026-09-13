# Part 10 — Traversal Matchers III — Types, TypeLocs & Templates

[← Part 9 — Traversal Matchers II — Statements & Expressions](part_9_traversal_stmts.md) | [Part 11 — Objective-C, OpenMP, CUDA & Blocks →](part_11_objc_openmp_cuda_blocks.md)

**Sample:** `manifests/trav_types.cpp` · flags: `-std=c++23`

## What You'll Learn
- How to step from a declaration or expression **into its type** with `hasType`, and why the *Decl-matcher* and *QualType-matcher* overloads see different things.
- The **sugar trap**: `hasType(recordDecl(…))` stops at a typedef, and how `hasCanonicalType` / `hasUnqualifiedDesugaredType` see through it.
- `hasDeclaration` — the one matcher that turns any of 17 node kinds back into the declaration behind it.
- One-level type traversal: `pointee`, `pointsTo`, `references`, `hasElementType`, `hasDecayedType`, `hasDeducedType`, `innerType`, `hasQualifier`, and friends.
- **TypeLocs**: a type *plus* where it was written — `hasTypeLoc`, `loc`, `hasReturnTypeLoc`, `hasPointeeLoc`, and the `…Loc` template-argument matchers.
- Nested-name specifiers (`A::B::`) and template arguments (`<int, R * 2>`), including how to tell `hasTemplateArgument` from `hasTemplateArgumentLoc`.

## The Big Picture

Types are never the starting point of a query. You reach them **from** a declaration
(`varDecl`, `fieldDecl`, `functionDecl`), **from** an expression, or **from** another
type. Every matcher in this part is one of those steps.

Clang keeps two views of every type. The **sugared** type is what the programmer wrote
(`XAlias`, `int_ref`, `N::M::D`); the **canonical** type is what it means after all
typedefs, `using`s, parentheses and qualifiers are stripped (`X`, `int &`, `D`).
Matchers walk the sugared view by default, so a `typedef` is a wall unless you say
otherwise:

```text
 VarDecl  "XAlias aliased;"
    │ hasType(…)                  ← Matcher<QualType>: the type *as written*
    ▼
 QualType XAlias  ── hasDeclaration ──▶  TypedefDecl XAlias      (sugar level)
    │ hasCanonicalType / hasUnqualifiedDesugaredType
    ▼
 Type X (RecordType) ── hasDeclaration ──▶  CXXRecordDecl X      (canonical level)
```

A **TypeLoc** is a type together with the source range where it was spelled. A
`QualType` matcher asks *what* the type is; a `TypeLoc` matcher can also ask *where*
and *how* it was spelled, and it nests the same way the syntax does
(`pointerTypeLoc(hasPointeeLoc(…))`). `loc(…)` is the bridge from a TypeLoc back to
a QualType matcher.

```text
 int *const pconst           TypeLoc tree:  QualifiedTypeLoc(const)
                                              └─ PointerTypeLoc(*)
                                                   └─ BuiltinTypeLoc(int)
```

Templates add two more axes. A `TemplateArgument` is the *resolved* argument
(`hasTemplateArgument`, reached from specializations and from
`templateSpecializationType`); a `TemplateArgumentLoc` is the *written* argument
(`hasTemplateArgumentLoc`, reached from `TypeLoc`s and from `declRefExpr`). Implicit
instantiations have resolved arguments but nothing written, which is why the two
families match different nodes.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/trav_types.cpp -- -std=c++23
```

---

## 10.1 — `hasType`: the workhorse

Almost every type query begins with `hasType`. It is overloaded twice over: the
*outer* node can be a `ValueDecl` (variables, fields, parameters, enumerators), an
`Expr`, a `CXXBaseSpecifier`, a `FriendDecl` or a `TypedefNameDecl`; the *inner*
matcher can be a **Decl matcher** (shorthand for "the declaration of this type") or a
**QualType matcher** (the type itself). The Decl form is convenient but stops at the
first declaration it finds — for `XAlias aliased;` that is the typedef, not the class.

### `hasType(Matcher<Decl> | Matcher<QualType> InnerMatcher)` — Matcher<CXXBaseSpecifier>, Matcher<Expr>, Matcher<FriendDecl>, Matcher<TypedefNameDecl>, Matcher<ValueDecl>

**ValueDecl, Decl-matcher form.** `X z;` on line 13 has a type whose declaration is
`class X`, so the variable matches. `XAlias aliased;` on line 9 does **not**: the
declaration behind its written type is the typedef, and `cxxRecordDecl` rejects it.

```text
clang-query> match varDecl(hasType(cxxRecordDecl(hasName("X"))))
```

**Expected:** 1 match — `z` at `trav_types.cpp:13`. `aliased` (line 9) is missed — that is the sugar trap.

**ValueDecl, QualType-matcher form.** Any `Matcher<QualType>` works inside: `asString`
compares the *written* spelling, so again only `z` matches.

```text
clang-query> match varDecl(hasType(asString("X")))
```

**Expected:** 1 match — `z` at `trav_types.cpp:13`.

To reach `aliased` through its typedef, ask for the typedef explicitly:

```text
clang-query> match varDecl(hasType(qualType(hasDeclaration(typedefDecl(hasName("XAlias"))))))
```

**Expected:** 1 match — `aliased` at `trav_types.cpp:9`.

**Expr.** Expressions have types too. The `x` inside `useX` (a `DeclRefExpr`) and the
implicit construction of `z` both have type `X`. Note that the expression `x` has type
`X`, not `X &` — expression types never carry references (they carry a value category
instead).

```text
clang-query> match expr(hasType(cxxRecordDecl(hasName("X"))))
```

**Expected:** 2 matches — the `DeclRefExpr` `x` at `trav_types.cpp:13:25` and the `CXXConstructExpr` for `z` at `13:30`.

```text
clang-query> match declRefExpr(hasType(references(cxxRecordDecl(hasName("X")))))
```

**Expected:** 0 matches — the *parameter* `x` is an `X &`, but the *expression* `x` is an lvalue of type `X`.

```text
clang-query> match parmVarDecl(hasName("x"), hasType(references(cxxRecordDecl(hasName("X")))))
```

**Expected:** 1 match — parameter `x` at `trav_types.cpp:13:11`.

**CXXBaseSpecifier.** A base specifier cannot be a top-level match in `clang-query`, so
reach it through `hasAnyBase` / `hasDirectBase` (Part 8). Both inner forms work:

```text
clang-query> match cxxRecordDecl(hasAnyBase(hasType(cxxRecordDecl(hasName("Base")))))
```

**Expected:** 2 matches — `Derived` at `trav_types.cpp:11` and `Sub` at `trav_types.cpp:89`.

```text
clang-query> match cxxRecordDecl(hasAnyBase(hasType(asString("Base"))))
```

**Expected:** 2 matches — `Derived` (line 11) and `Sub` (line 89).

**FriendDecl.** `friend class X;` names a type; `asString` sees the elaborated spelling
`class X` here because the keyword was written.

```text
clang-query> match friendDecl(hasType(cxxRecordDecl(hasName("X"))))
```

**Expected:** 1 match — the friend declaration at `trav_types.cpp:12:11`.

```text
clang-query> match friendDecl(hasType(asString("class X")))
```

**Expected:** 1 match — the same friend declaration at `trav_types.cpp:12:11`.

**TypedefNameDecl.** For a typedef or alias, `hasType` looks at the *underlying* type
(only the QualType form exists here).

```text
clang-query> match typedefDecl(hasType(asString("int")))
```

**Expected:** 1 match — `typedef int Int` at `trav_types.cpp:8`.

```text
clang-query> match typedefNameDecl(hasType(asString("X")))
```

**Expected:** 1 match — `typedef X XAlias` at `trav_types.cpp:7`.

### `hasCanonicalType(Matcher<QualType> InnerMatcher)` — Matcher<QualType>

Replaces the sugared type with its canonical form before matching. `seedRef` is
declared with the typedef `int_ref`; its written type is a `TypedefType`, not a
`ReferenceType`, so a plain `referenceType()` fails and the canonical one succeeds.

```text
clang-query> match varDecl(hasName("seedRef"), hasType(qualType(referenceType())))
```

**Expected:** 0 matches — the written type is the typedef `int_ref`.

```text
clang-query> match varDecl(hasName("seedRef"), hasType(qualType(hasCanonicalType(referenceType()))))
```

**Expected:** 1 match — `seedRef` at `trav_types.cpp:16`.

### `hasUnqualifiedDesugaredType(Matcher<Type> InnerMatcher)` — Matcher<Type>

The reference's recommended cure for the sugar trap: strip every layer of sugar *and*
the top-level qualifiers, then hand the bare `Type` to the inner matcher. Now both the
alias-declared `aliased` and the plainly-declared `z` match.

```text
clang-query> match varDecl(hasType(hasUnqualifiedDesugaredType(
                 recordType(hasDeclaration(cxxRecordDecl(hasName("X")))))))
```

**Expected:** 2 matches — `aliased` at `trav_types.cpp:9` and `z` at `trav_types.cpp:13`.

---

## 10.2 — `hasDeclaration`: from a node to the decl behind it

Seventeen node kinds carry a "declaration associated with me". For **types** it is the
declaration of the (sugared) type — a typedef, a class, an enum, a template parameter,
a using-shadow. For **expressions** it is whatever the expression refers to: the callee
of a `CallExpr`, the member of a `MemberExpr`, the constructor of a `CXXConstructExpr`,
the `operator new` of a `CXXNewExpr`, the label of an `AddrLabelExpr`. For a
`LabelStmt` it is the `LabelDecl`. One idea, one matcher, one inner `Matcher<Decl>`.

### `hasDeclaration(Matcher<Decl> InnerMatcher)` — Matcher<AddrLabelExpr>, Matcher<CXXConstructExpr>, Matcher<CXXNewExpr>, Matcher<CallExpr>, Matcher<DeclRefExpr>, Matcher<EnumType>, Matcher<InjectedClassNameType>, Matcher<LabelStmt>, Matcher<MemberExpr>, Matcher<QualType>, Matcher<RecordType>, Matcher<TagType>, Matcher<TemplateSpecializationType>, Matcher<TemplateTypeParmType>, Matcher<TypedefType>, Matcher<UnresolvedUsingType>, Matcher<UsingType>

**Expressions (6 overloads).** Start with the everyday ones — a reference to an
enumerator, a call, a member access, a constructor call, a `new`, and a label address.

```text
clang-query> match declRefExpr(hasDeclaration(enumConstantDecl(hasName("Green"))))
```

**Expected:** 1 match — the `Green` in `Color color = Green;` at `trav_types.cpp:20:15`.

```text
clang-query> match callExpr(hasDeclaration(functionDecl(hasName("readValue"))))
```

**Expected:** 1 match — the call inside `callIt` at `trav_types.cpp:30:28`.

`node.value` appears twice in the AST: once in `readValue` and once inside `Node`'s
*implicitly defined* copy constructor (which `Node local(node)` forces Clang to
synthesize). Switch to the source-only traversal mode to see just the one you wrote.

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match memberExpr(hasDeclaration(fieldDecl(hasName("value"))))
```

**Expected:** 1 match — `node.value` at `trav_types.cpp:27:27`.

```text
clang-query> match cxxConstructExpr(hasDeclaration(cxxConstructorDecl(isCopyConstructor())))
```

**Expected:** 1 match — `Node local(node)` at `trav_types.cpp:29:26`.

```text
clang-query> match cxxNewExpr(hasDeclaration(functionDecl(hasName("operator new"))))
```

**Expected:** 1 match — `new Node{2, nullptr}` at `trav_types.cpp:28:28` (the declaration is Clang's implicit global `operator new`).

```text
clang-query> match addrLabelExpr(hasDeclaration(labelDecl(hasName("done"))))
```

**Expected:** 1 match — `&&done` at `trav_types.cpp:33:18`.

**Statements (1 overload).** The label itself.

```text
clang-query> match labelStmt(hasDeclaration(labelDecl(hasName("done"))))
```

**Expected:** 1 match — `done:` at `trav_types.cpp:36`.

**QualType (1 overload).** On a `QualType` the declaration is that of the *sugared*
type — for `aliased` that is the typedef, exactly as in 10.1.

```text
clang-query> match varDecl(hasName("aliased"), hasType(qualType(hasDeclaration(typedefDecl()))))
```

**Expected:** 1 match — `aliased` at `trav_types.cpp:9`.

**Concrete type nodes (9 overloads).** Once you narrow to a specific type class, the
declaration is the obvious one: `enumType` → `enumDecl`, `recordType` → `recordDecl`,
`tagType` → either, `templateTypeParmType` → the `T` of a template,
`injectedClassNameType` → the template's own class, `templateSpecializationType` → the
specialization, `typedefType` → the typedef, `usingType` → the using-shadow, and
`unresolvedUsingType` → a `using typename T::type;` inside a template.

```text
clang-query> match varDecl(hasType(enumType(hasDeclaration(enumDecl(hasName("Color"))))))
```

**Expected:** 1 match — `color` at `trav_types.cpp:20`.

```text
clang-query> match varDecl(hasType(recordType(hasDeclaration(recordDecl(hasName("Node"))))))
```

**Expected:** 2 matches — `node` at `trav_types.cpp:26` and `local` at `trav_types.cpp:29:21`.

```text
clang-query> match varDecl(hasType(tagType(hasDeclaration(tagDecl(hasName("Node"))))))
```

**Expected:** 2 matches — the same `node` (line 26) and `local` (line 29); `tagType` covers records and enums alike.

```text
clang-query> match fieldDecl(hasType(templateTypeParmType(hasDeclaration(templateTypeParmDecl(hasName("T"))))))
```

**Expected:** 1 match — `T held;` inside `Wrap` at `trav_types.cpp:41:3`.

```text
clang-query> match parmVarDecl(hasType(injectedClassNameType(hasDeclaration(cxxRecordDecl(hasName("Wrap"))))))
```

**Expected:** 1 match — the parameter `other` of `Wrap take(Wrap other)` at `trav_types.cpp:42:13`.

```text
clang-query> match varDecl(hasType(templateSpecializationType(
                 hasDeclaration(classTemplateSpecializationDecl(hasName("Wrap"))))))
```

**Expected:** 1 match — `Wrap<int> wrapped` at `trav_types.cpp:44`.

```text
clang-query> match varDecl(hasType(typedefType(hasDeclaration(typedefDecl(hasName("XAlias"))))))
```

**Expected:** 1 match — `aliased` at `trav_types.cpp:9`.

```text
clang-query> match varDecl(hasType(usingType(hasDeclaration(usingShadowDecl()))))
```

**Expected:** 1 match — `Widget widget` at `trav_types.cpp:54` (`Widget` is visible only through `using lib::Widget`).

`clang-query` 22 has no `unresolvedUsingType()` node matcher, so reach that overload
through the `QualType` one: the field `type field;` in `Inherit` has an
`UnresolvedUsingType` whose declaration is the `using typename T::type;` on line 47.

```text
clang-query> match fieldDecl(hasType(hasDeclaration(unresolvedUsingTypenameDecl())))
```

**Expected:** 1 match — `type field;` at `trav_types.cpp:48:3`.

---

## 10.3 — Pointers, references, arrays & one-level sugar

Each matcher here peels exactly one layer off a type: the pointee of a pointer, the
element of an array, the deduced type behind `auto`, the inner type of a
parenthesized declarator. Combine them to describe any declarator shape.

### `pointee(Matcher<Type>)` — Matcher<MemberPointerType>, Matcher<PointerType>, Matcher<ReferenceType>

Narrows a pointer-like *type node* by what it points at. Use it after `pointerType()`,
`referenceType()` or `memberPointerType()`.

```text
clang-query> match varDecl(hasType(pointerType(pointee(isConstQualified(), isInteger()))))
```

**Expected:** 1 match — `int const *cip` at `trav_types.cpp:59`.

```text
clang-query> match varDecl(hasType(referenceType(pointee(isInteger()))), hasGlobalStorage())
```

**Expected:** 2 matches — `iref` at `trav_types.cpp:61` and `xx` at `trav_types.cpp:99` (`seedRef` is hidden behind its typedef).

```text
clang-query> match varDecl(hasType(memberPointerType(pointee(isInteger()))))
```

**Expected:** 1 match — `int Node::*fieldPtr` at `trav_types.cpp:62`.

### `pointsTo(Matcher<Decl> | Matcher<QualType> InnerMatcher)` — Matcher<QualType>

The `QualType`-level cousin of `pointee`: "is a pointer, and the pointee matches".
The Decl overload matches the pointee's declaration; the QualType overload matches the
pointee type itself.

```text
clang-query> match fieldDecl(hasType(pointsTo(recordDecl(hasName("Node")))))
```

**Expected:** 1 match — `Node *next` at `trav_types.cpp:23:3`.

```text
clang-query> match functionDecl(returns(pointsTo(recordDecl(hasName("Node")))))
```

**Expected:** 2 matches — `Node::self` at `trav_types.cpp:24:3` and `make` at `trav_types.cpp:28`.

```text
clang-query> match varDecl(hasType(pointsTo(asString("const float"))))
```

**Expected:** 1 match — `float const *cfp` at `trav_types.cpp:60`.

### `references(Matcher<Decl> | Matcher<QualType> InnerMatcher)` — Matcher<QualType>

Same pair of overloads for reference types. Class `X` gets implicit copy/move
constructors whose parameters are `const X &` / `X &&`; the source-only traversal mode
hides them so only the parameter you wrote shows up.

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match varDecl(hasType(references(cxxRecordDecl(hasName("X")))))
```

**Expected:** 1 match — parameter `x` of `useX` at `trav_types.cpp:13:11`.

```text
clang-query> match varDecl(hasType(references(isInteger())))
```

**Expected:** 3 matches — `seedRef` (line 16), `iref` (line 61) and `xx` (line 99). Unlike `referenceType()`, `references` looks through the `int_ref` typedef.

### `hasElementType(Matcher<Type>)` — Matcher<ArrayType>, Matcher<ComplexType>

Arrays and `_Complex` types both have an element type.

```text
clang-query> match varDecl(hasType(arrayType(hasElementType(builtinType()))))
```

**Expected:** 2 matches — `int arr[3]` at `trav_types.cpp:63` and the VLA `a` at `trav_types.cpp:68:19`.

```text
clang-query> match varDecl(hasType(arrayType(hasElementType(pointerType()))))
```

**Expected:** 1 match — `int *parr[3]` at `trav_types.cpp:64`.

```text
clang-query> match varDecl(hasType(complexType(hasElementType(builtinType()))))
```

**Expected:** 1 match — `_Complex float cplx` at `trav_types.cpp:65`.

### `hasValueType(Matcher<Type>)` — Matcher<AtomicType>

The type wrapped by `_Atomic(…)`.

```text
clang-query> match varDecl(hasType(atomicType(hasValueType(isInteger()))))
```

**Expected:** 1 match — `_Atomic(int) atomInt` at `trav_types.cpp:66` (not `atomFloat`).

### `hasSizeExpr(Matcher<Expr> InnerMatcher)` — Matcher<VariableArrayType>

A variable-length array remembers the expression that sized it.

```text
clang-query> match varDecl(hasType(variableArrayType(hasSizeExpr(
                 ignoringImpCasts(declRefExpr(to(varDecl(hasName("b")))))))))
```

**Expected:** 1 match — `int a[b]` at `trav_types.cpp:68:19`.

### `hasDecayedType(Matcher<QualType> InnerType)` — Matcher<DecayedType>

An array or function parameter *decays* to a pointer; the `DecayedType` keeps both
the original and the decayed form. This matches the decayed one.

```text
clang-query> match parmVarDecl(hasType(decayedType(hasDecayedType(pointerType()))))
```

**Expected:** 1 match — `int param[]` at `trav_types.cpp:69:13`.

### `hasDeducedType(Matcher<Type>)` — Matcher<AutoType>

What `auto` turned into. (There is no TypeLoc for the deduced type — nothing was
written.)

```text
clang-query> match varDecl(hasType(autoType(hasDeducedType(isInteger()))))
```

**Expected:** 2 matches — `deducedInt` at `trav_types.cpp:70` and `tmpInt` at `trav_types.cpp:90` (`deducedDouble` is excluded).

### `innerType(Matcher<Type>)` — Matcher<ParenType>

The parentheses in `int (*p)(int)` create a `ParenType`; `innerType` looks inside them.
This is how you tell a pointer-to-function from a pointer-to-array.

```text
clang-query> match varDecl(hasType(pointsTo(parenType(innerType(functionType())))))
```

**Expected:** 1 match — `ptrToFunc` at `trav_types.cpp:73`.

```text
clang-query> match varDecl(hasType(pointsTo(parenType(innerType(arrayType())))))
```

**Expected:** 1 match — `ptrToArray` at `trav_types.cpp:72`.

### `hasReplacementType(Matcher<Type>)` — Matcher<SubstTemplateTypeParmType>

Inside an instantiation, a `T` that has been replaced keeps a `SubstTemplateTypeParmType`
wrapper recording what replaced it. `F(seed)` instantiates `F<int>`, so `t` is an `int`
wearing that wrapper.

```text
clang-query> match parmVarDecl(hasType(substTemplateTypeParmType(hasReplacementType(asString("int")))))
```

**Expected:** 1 match — parameter `t` of the `F<int>` instantiation at `trav_types.cpp:74:32`.

### `hasQualifier(Matcher<NestedNameSpecifier> InnerMatcher)` — Matcher<Type>

A type written as `N::M::D` carries the qualifier `N::M::` as a `NestedNameSpecifier`
(details in 10.5). `hasQualifier` hands that specifier to an inner matcher.

```text
clang-query> match varDecl(hasType(hasQualifier(hasPrefix(specifiesNamespace(hasName("N"))))))
```

**Expected:** 1 match — `N::M::D d` at `trav_types.cpp:77`.

```text
clang-query> match varDecl(hasType(type(hasQualifier(specifiesNamespace(hasName("M"))))))
```

**Expected:** 1 match — the same `d` at `trav_types.cpp:77`; the innermost specifier is `M::`.

### `hasUnderlyingType(Matcher<QualType> Inner)` — Matcher<Type>

For `decltype(expr)` (and similar wrappers) — the type that was computed.

```text
clang-query> match varDecl(hasType(decltypeType(hasUnderlyingType(isInteger()))))
```

**Expected:** 1 match — `decltype(1) dl` at `trav_types.cpp:78`.

### `ignoringParens(Matcher<QualType> InnerMatcher)` — Matcher<QualType>

Strips `ParenType` layers before matching — the QualType-level alternative to spelling
out `parenType(innerType(…))`.

```text
clang-query> match varDecl(hasType(pointerType(pointee(ignoringParens(functionType())))))
```

**Expected:** 1 match — `ptrToFunc` at `trav_types.cpp:73`.

### `throughUsingDecl(Matcher<UsingShadowDecl> Inner)` — Matcher<DeclRefExpr>, Matcher<UsingType>

Matches a name that was found *via* a `using` declaration; the inner matcher sees the
`UsingShadowDecl`, whose `hasTargetDecl` (Part 8) is the real entity.

```text
clang-query> match declRefExpr(throughUsingDecl(hasTargetDecl(functionDecl(hasName("helper")))))
```

**Expected:** 1 match — the `helper` in `helper()` at `trav_types.cpp:55:16`.

```text
clang-query> match varDecl(hasType(usingType(throughUsingDecl(hasTargetDecl(hasName("Widget"))))))
```

**Expected:** 1 match — `Widget widget` at `trav_types.cpp:54`.

---

## 10.4 — TypeLocs: type + where it was written

A `TypeLoc` mirrors the declarator syntax: `int *const p` is a `QualifiedTypeLoc`
around a `PointerTypeLoc` around a `BuiltinTypeLoc`. `hasTypeLoc` enters that tree
from a node that wrote a type; `loc(…)` converts back to a `QualType` matcher when you
only care *what* the type is. Explicit and implicit casts also name a destination type,
so they close this section.

### `hasTypeLoc(Matcher<TypeLoc> Inner)` — Matcher<CXXBaseSpecifier>, Matcher<CXXCtorInitializer>, Matcher<CXXFunctionalCastExpr>, Matcher<CXXNewExpr>, Matcher<CXXTemporaryObjectExpr>, Matcher<CXXUnresolvedConstructExpr>, Matcher<CompoundLiteralExpr>, Matcher<DeclaratorDecl>, Matcher<ExplicitCastExpr>, Matcher<TemplateArgumentLoc>, Matcher<TypedefNameDecl>

Eleven node kinds in this part *write* a type somewhere: every declarator, typedefs,
base specifiers, base-class constructor initializers, `T(…)` casts and temporaries,
`(T){…}` compound literals, `new T`, C-style casts, and template arguments. The
source-only traversal mode keeps template instantiations (which re-use the pattern's
TypeLoc) out of the counts.

**DeclaratorDecl** — fields, variables, parameters, functions:

```text
clang-query> set traversal IgnoreUnlessSpelledInSource
clang-query> match fieldDecl(hasTypeLoc(loc(asString("int"))))
```

**Expected:** 5 matches — `Node::value` (line 22), `Foo::m` (line 85), `Point::px` and `Point::py` (line 93), `Rec::next` (line 123).

**TypedefNameDecl:**

```text
clang-query> match typedefNameDecl(hasTypeLoc(loc(asString("X"))))
```

**Expected:** 1 match — `typedef X XAlias` at `trav_types.cpp:7`.

**CXXBaseSpecifier** (via `hasAnyBase`) and **CXXCtorInitializer** (via
`hasAnyConstructorInitializer`, Part 8) — only *base* or delegating initializers
carry a TypeLoc, member initializers do not:

```text
clang-query> match cxxRecordDecl(hasAnyBase(hasTypeLoc(loc(asString("Base")))))
```

**Expected:** 2 matches — `Derived` (line 11) and `Sub` (line 89).

```text
clang-query> match cxxConstructorDecl(hasAnyConstructorInitializer(hasTypeLoc(loc(asString("Base")))))
```

**Expected:** 1 match — `Sub() : Base() {}` at `trav_types.cpp:89:21`.

**CXXFunctionalCastExpr / CXXTemporaryObjectExpr / CXXUnresolvedConstructExpr** — the
three faces of `T(args)`: one argument is a functional cast, several arguments to a
class is a temporary object, and a dependent `T` is unresolved:

```text
clang-query> match varDecl(hasName("tmpInt"), hasInitializer(cxxFunctionalCastExpr(hasTypeLoc(loc(asString("int"))))))
```

**Expected:** 1 match — `auto tmpInt = int(3)` at `trav_types.cpp:90`.

```text
clang-query> match cxxTemporaryObjectExpr(hasTypeLoc(loc(asString("Foo"))))
```

**Expected:** 1 match — `Foo(1, 2)` at `trav_types.cpp:91:15`.

```text
clang-query> match cxxUnresolvedConstructExpr(hasTypeLoc(loc(asString("T"))))
```

**Expected:** 2 matches — `T(1)` in `build` at `trav_types.cpp:92:42` and `T(0)` in `zero` at `trav_types.cpp:130:42`.

**CompoundLiteralExpr, CXXNewExpr, ExplicitCastExpr:**

```text
clang-query> match compoundLiteralExpr(hasTypeLoc(loc(asString("Point"))))
```

**Expected:** 1 match — `(Point){1, 2}` at `trav_types.cpp:94:12`.

```text
clang-query> match cxxNewExpr(hasTypeLoc(loc(asString("Node"))))
```

**Expected:** 1 match — `new Node{2, nullptr}` at `trav_types.cpp:28:28`.

```text
clang-query> match explicitCastExpr(hasTypeLoc(loc(asString("long"))))
```

**Expected:** 1 match — `(long)seed` at `trav_types.cpp:95:16`.

**TemplateArgumentLoc** — a written template argument that is a type:

```text
clang-query> match templateArgumentLoc(hasTypeLoc(loc(asString("double"))))
```

**Expected:** 5 matches — the `double` written in `Pair<double, int>` (line 109), `Pair<int, double>` (line 110), `Vec<double>` (line 112), `tf<double>` (line 115) and `zero<double>` (line 131).

### `hasReturnTypeLoc(Matcher<TypeLoc> ReturnMatcher)` — Matcher<FunctionDecl>

The TypeLoc of a function's return type.

```text
clang-query> match functionDecl(hasReturnTypeLoc(loc(asString("int"))))
```

**Expected:** 5 matches — `readValue` (line 27), `callIt` (line 30), `jumpAround` (line 32), `lib::helper` (line 51) and `retInt` (line 82).

### `returns(Matcher<QualType> InnerMatcher)` — Matcher<FunctionDecl>

The same question at the `QualType` level — use this when you do not care how the
return type was spelled.

```text
clang-query> match functionDecl(returns(asString("int")))
```

**Expected:** 5 matches — the same five functions as above.

```text
clang-query> match functionDecl(hasName("retVoid"), returns(voidType()))
```

**Expected:** 1 match — `retVoid` at `trav_types.cpp:83`.

### `loc(Matcher<QualType> | Matcher<NestedNameSpecifier> InnerMatcher)` — Matcher<NestedNameSpecifierLoc>, Matcher<TypeLoc>

The bridge from a "Loc" node to its location-less counterpart: `loc(qualTypeMatcher)`
matches a `TypeLoc` whose type matches, and `loc(nnsMatcher)` matches a
`NestedNameSpecifierLoc` whose specifier matches. You have been using the first form
inside every `hasTypeLoc` above.

```text
clang-query> match typeLoc(loc(asString("Color")))
```

**Expected:** 1 match — the `Color` written in `Color color = Green;` at `trav_types.cpp:20`.

```text
clang-query> match nestedNameSpecifierLoc(loc(specifiesNamespace(hasName("ns"))))
```

**Expected:** 1 match — the `ns::` in `ns::S nss;` at `trav_types.cpp:105`.

### `hasPointeeLoc(Matcher<TypeLoc> PointeeMatcher)` — Matcher<PointerTypeLoc>

Descends from a `*` to the TypeLoc it applies to.

```text
clang-query> match varDecl(hasTypeLoc(pointerTypeLoc(hasPointeeLoc(loc(asString("int"))))))
```

**Expected:** 1 match — `int *ip` at `trav_types.cpp:58` (`cip`'s pointee is `const int`, and `parr`'s outer TypeLoc is an array).

```text
clang-query> match pointerTypeLoc(hasPointeeLoc(loc(asString("int"))))
```

**Expected:** 2 matches — the `*` in `ip` (line 58) and the element `*` inside `int *parr[3]` (line 64).

### `hasReferentLoc(Matcher<TypeLoc> ReferentMatcher)` — Matcher<ReferenceTypeLoc>

The `&` counterpart of `hasPointeeLoc`.

```text
clang-query> match referenceTypeLoc(hasReferentLoc(loc(asString("int"))))
```

**Expected:** 3 matches — `typedef int &int_ref` (line 14), `iref` (line 61) and `xx` (line 99).

### `hasUnqualifiedLoc(Matcher<TypeLoc> InnerMatcher)` — Matcher<QualifiedTypeLoc>

A `const`/`volatile` written on a type produces a `QualifiedTypeLoc` wrapper; this steps
inside it. `int *const pconst` qualifies a pointer, `const int cy` qualifies a builtin.

```text
clang-query> match qualifiedTypeLoc(hasUnqualifiedLoc(pointerTypeLoc()))
```

**Expected:** 1 match — `int *const pconst` at `trav_types.cpp:97`.

### `hasTemplateArgumentLoc(unsigned Index, Matcher<TemplateArgumentLoc> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<DeclRefExpr>, Matcher<FunctionDecl>, Matcher<OverloadExpr>, Matcher<TemplateSpecializationTypeLoc>, Matcher<VarTemplateSpecializationDecl>

The *written* n'th template argument. Because it needs something written, it matches
`Pair<double, int>` as a TypeLoc, the `<int>` on `tf<int>()` and `zero<int>`, and
**explicit** specializations (`Vec<double>`, `tf<double>`) — but not implicit
instantiations, which wrote nothing.

```text
clang-query> match varDecl(hasTypeLoc(templateSpecializationTypeLoc(
                 hasTemplateArgumentLoc(0, hasTypeLoc(loc(asString("double")))))))
```

**Expected:** 1 match — `Pair<double, int> pdi` at `trav_types.cpp:109` (not `pid`, whose `double` is argument 1).

```text
clang-query> match declRefExpr(hasTemplateArgumentLoc(0, hasTypeLoc(loc(asString("int")))))
```

**Expected:** 2 matches — `tf<int>` at `trav_types.cpp:116:17` and `zero<int>` at `trav_types.cpp:132:10`.

```text
clang-query> match functionDecl(hasTemplateArgumentLoc(0, hasTypeLoc(loc(asString("double")))))
```

**Expected:** 1 match — the explicit specialization `tf<double>` at `trav_types.cpp:115`.

```text
clang-query> match classTemplateSpecializationDecl(hasTemplateArgumentLoc(0, hasTypeLoc(loc(asString("double")))))
```

**Expected:** 1 match — the explicit specialization `Vec<double>` at `trav_types.cpp:112`.

Two overloads are listed in the reference but out of reach in `clang-query` 22: the
`OverloadExpr` variant is not registered for the dynamic DSL (`unresolvedLookupExpr(
hasTemplateArgumentLoc(…))` reports "Incorrect type for arg 1"), and there is no
`varTemplateSpecializationDecl()` node matcher, so `zero<double>` can only be reached
through the `declRefExpr` form shown above.

### `hasAnyTemplateArgumentLoc(Matcher<TemplateArgumentLoc> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<DeclRefExpr>, Matcher<FunctionDecl>, Matcher<OverloadExpr>, Matcher<TemplateSpecializationTypeLoc>, Matcher<VarTemplateSpecializationDecl>

Like `hasTemplateArgumentLoc` without the index — any written argument may match.
The same two overloads (`OverloadExpr`, `VarTemplateSpecializationDecl`) are
unreachable from `clang-query` 22.

```text
clang-query> match varDecl(hasTypeLoc(templateSpecializationTypeLoc(
                 hasAnyTemplateArgumentLoc(hasTypeLoc(loc(asString("double")))))))
```

**Expected:** 2 matches — `pdi` (line 109) and `pid` (line 110).

```text
clang-query> match templateSpecializationTypeLoc(hasAnyTemplateArgumentLoc(hasTypeLoc(loc(asString("int")))))
```

**Expected:** 5 matches — `Wrap<int>` (line 44), `Pair<double, int>` (line 109), `Pair<int, double>` (line 110), `Vec<int>` (line 113), `Matrix<int, …>` (line 119).

```text
clang-query> match declRefExpr(hasAnyTemplateArgumentLoc(hasTypeLoc(loc(asString("int")))))
```

**Expected:** 2 matches — `tf<int>` (line 116) and `zero<int>` (line 132).

```text
clang-query> match functionDecl(hasAnyTemplateArgumentLoc(hasTypeLoc(loc(asString("double")))))
```

**Expected:** 1 match — `tf<double>` at `trav_types.cpp:115`.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgumentLoc(hasTypeLoc(loc(asString("double")))))
```

**Expected:** 1 match — `Vec<double>` at `trav_types.cpp:112`.

### `hasDestinationType(Matcher<QualType> InnerMatcher)` — Matcher<ExplicitCastExpr>

The type an explicit cast converts *to*. (Clang calls implicit conversions "casts" as
well; this matcher is only for the ones you wrote.)

```text
clang-query> match explicitCastExpr(hasDestinationType(asString("long")))
```

**Expected:** 1 match — `(long)seed` at `trav_types.cpp:95:16`.

```text
clang-query> match cStyleCastExpr(hasDestinationType(voidType()))
```

**Expected:** 3 matches — the three `(void)…` silencing casts at lines 13, 29 and 68.

### `hasImplicitDestinationType(Matcher<QualType> InnerMatcher)` — Matcher<ImplicitCastExpr>

The same for implicit conversions. `double implicitD = seed;` converts `int` to
`double` without a single character of syntax.

```text
clang-query> match varDecl(hasName("implicitD"),
                 hasInitializer(implicitCastExpr(hasImplicitDestinationType(asString("double")))))
```

**Expected:** 1 match — `implicitD` at `trav_types.cpp:96`.

---

## 10.5 — Nested-name specifiers

`A::B::C` is one type name with a two-level qualifier `A::B::`. Clang stores the
qualifier as a chain of `NestedNameSpecifier`s — `A::B::` has prefix `A::` — and each
link either *specifies a type* (`A::`, `A::B::`) or *specifies a namespace* (`ns::`).
`NestedNameSpecifier` nodes are uniqued and carry no location (so their matches print
without a source line); `NestedNameSpecifierLoc` is the located version, and `loc(…)`
converts between the two.

### `hasPrefix(Matcher<NestedNameSpecifier> | Matcher<NestedNameSpecifierLoc> InnerMatcher)` — Matcher<NestedNameSpecifierLoc>, Matcher<NestedNameSpecifier>

Steps outward one level: from `A::B::` to `A::`.

```text
clang-query> match nestedNameSpecifier(hasPrefix(specifiesType(asString("A"))))
```

**Expected:** 1 match — the specifier `A::B::` (no location is printed for a bare `NestedNameSpecifier`).

```text
clang-query> match nestedNameSpecifierLoc(hasPrefix(loc(specifiesType(asString("A")))))
```

**Expected:** 1 match — `A::B::` in `A::B::C abc;` at `trav_types.cpp:103`.

### `specifiesType(Matcher<QualType> InnerMatcher)` — Matcher<NestedNameSpecifier>

The type a specifier names, without qualifiers.

```text
clang-query> match nestedNameSpecifier(specifiesType(hasDeclaration(cxxRecordDecl(hasName("A")))))
```

**Expected:** 1 match — the specifier `A::`.

```text
clang-query> match nestedNameSpecifierLoc(loc(specifiesType(hasDeclaration(cxxRecordDecl(hasName("B"))))))
```

**Expected:** 1 match — `A::B::` at `trav_types.cpp:103`.

### `specifiesTypeLoc(Matcher<TypeLoc> InnerMatcher)` — Matcher<NestedNameSpecifierLoc>

The located version: the specifier's type as a `TypeLoc`. (`loc(type(…))` does not
build in `clang-query`; wrap the inner matcher in `qualType(…)` as shown.)

```text
clang-query> match nestedNameSpecifierLoc(specifiesTypeLoc(
                 loc(qualType(hasDeclaration(cxxRecordDecl(hasName("A")))))))
```

**Expected:** 1 match — `A::` at `trav_types.cpp:103`.

### `specifiesNamespace(Matcher<NamespaceDecl> InnerMatcher)` — Matcher<NestedNameSpecifier>

For qualifiers that name a namespace rather than a type.

```text
clang-query> match nestedNameSpecifier(specifiesNamespace(hasName("ns")))
```

**Expected:** 1 match — the specifier `ns::`.

```text
clang-query> match nestedNameSpecifierLoc(loc(specifiesNamespace(hasName("M"))))
```

**Expected:** 1 match — `N::M::` in `N::M::D d;` at `trav_types.cpp:77`.

---

## 10.6 — Template arguments

A resolved `TemplateArgument` is one of: a **type** (`refersToType`), a
**declaration** such as `&Rec::next` (`refersToDeclaration`), an **integral value**
such as `42` (`refersToIntegralType` checks its type), a **template** such as `Vec`
(`refersToTemplate`), or an **expression** that is still an expression, such as
`R * 2` (`isExpr`). You get at the arguments from a class template specialization, a
function template specialization, a variable template specialization, or a
`templateSpecializationType`.

Note that a `classTemplateSpecializationDecl` for an *implicit* instantiation is
reported at the template's own line (`Pair` at 108), not where `Pair<double, int>` was
used — go through `varDecl(hasType(templateSpecializationType(…)))` when you want the
use site.

### `hasTemplateArgument(unsigned N, Matcher<TemplateArgument> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<FunctionDecl>, Matcher<TemplateSpecializationType>, Matcher<VarTemplateSpecializationDecl>

The n'th resolved argument.

```text
clang-query> match classTemplateSpecializationDecl(hasTemplateArgument(1, refersToType(asString("int"))))
```

**Expected:** 1 match — the specialization `Pair<double, int>`, reported at `trav_types.cpp:108`.

```text
clang-query> match functionDecl(hasTemplateArgument(0, refersToType(asString("int"))))
```

**Expected:** 2 matches — the instantiations `F<int>` (line 74) and `tf<int>` (line 114).

```text
clang-query> match varDecl(hasType(templateSpecializationType(hasTemplateArgument(0, refersToType(asString("double"))))))
```

**Expected:** 1 match — `pdi` at `trav_types.cpp:109`.

The `VarTemplateSpecializationDecl` overload (for `zero<int>`) is real but unreachable:
`clang-query` 22 registers no `varTemplateSpecializationDecl()` node matcher, and the
DSL refuses `varDecl(hasTemplateArgument(…))` because the argument is narrower than
`VarDecl`.

### `hasAnyTemplateArgument(Matcher<TemplateArgument> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<FunctionDecl>, Matcher<TemplateSpecializationType>, Matcher<VarTemplateSpecializationDecl>

Any resolved argument, at any position. Same four hosts; the variable-template one is
unreachable for the same reason as above.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgument(refersToType(asString("int"))))
```

**Expected:** 5 matches — `Wrap<int>` (line 40), both `Pair` instantiations (line 108, twice), `Vec<int>` (line 111) and `Matrix<int, 4, 8>` (line 117).

```text
clang-query> match functionDecl(hasAnyTemplateArgument(refersToType(asString("int"))))
```

**Expected:** 2 matches — `F<int>` (line 74) and `tf<int>` (line 114).

```text
clang-query> match varDecl(hasType(templateSpecializationType(hasAnyTemplateArgument(refersToType(asString("double"))))))
```

**Expected:** 2 matches — `pdi` (line 109) and `pid` (line 110).

### `forEachTemplateArgument(Matcher<TemplateArgument> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>, Matcher<FunctionDecl>, Matcher<TemplateSpecializationType>, Matcher<VarTemplateSpecializationDecl>

Produces one match *per argument* that satisfies the inner matcher. `clang-query`
collapses matches that bind exactly the same nodes, so bind something inside to see the
multiplicity: `Matrix<int, R * 2, R * 4>` then counts twice.

```text
clang-query> match varDecl(hasType(templateSpecializationType(
                 forEachTemplateArgument(isExpr(expr().bind("arg"))))))
```

**Expected:** 4 matches — `mat` (line 119) twice, for `R * 2` and `R * 4`; `chain` (line 125) for `&Rec::next`; `c42` (line 127) for `42`.

```text
clang-query> match functionDecl(hasName("fwd"), forEachTemplateArgument(refersToType(builtinType().bind("t"))))
```

**Expected:** 2 matches — the instantiation `fwd<unsigned, bool>` at `trav_types.cpp:120:35`, once for `unsigned` and once for `bool`.

### `hasSpecializedTemplate(Matcher<ClassTemplateDecl> InnerMatcher)` — Matcher<ClassTemplateSpecializationDecl>

From a specialization back to the primary template it specializes.

```text
clang-query> match classTemplateSpecializationDecl(hasSpecializedTemplate(classTemplateDecl(hasName("Vec"))))
```

**Expected:** 2 matches — the implicit `Vec<int>` (reported at line 111) and the explicit `Vec<double>` (line 112).

### `refersToType(Matcher<QualType> InnerMatcher)` — Matcher<TemplateArgument>

A type argument.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgument(refersToType(asString("double"))))
```

**Expected:** 3 matches — the two `Pair` instantiations (line 108, twice) and `Vec<double>` (line 112).

### `refersToDeclaration(Matcher<Decl> InnerMatcher)` — Matcher<TemplateArgument>

A declaration argument — here the pointer-to-member `&Rec::next`.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgument(
                 refersToDeclaration(fieldDecl(hasName("next")))))
```

**Expected:** 1 match — the specialization `Chain<&Rec::next>`, reported at `trav_types.cpp:124`.

### `refersToIntegralType(Matcher<QualType> InnerMatcher)` — Matcher<TemplateArgument>

An integral (non-type) argument whose *type* matches — `42` is an `int`.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgument(refersToIntegralType(asString("int"))))
```

**Expected:** 1 match — the specialization `Const<42>`, reported at `trav_types.cpp:126`.

### `refersToTemplate(Matcher<TemplateName> InnerMatcher)` — Matcher<TemplateArgument>

A template template argument — `Vec` passed to `Holder`.

```text
clang-query> match classTemplateSpecializationDecl(hasAnyTemplateArgument(refersToTemplate(templateName())))
```

**Expected:** 1 match — the specialization `Holder<Vec>`, reported at `trav_types.cpp:128`.

### `isExpr(Matcher<Expr> InnerMatcher)` — Matcher<TemplateArgument>

A *sugared* argument that is still an expression — available on the
`templateSpecializationType` written at the use site, where `&Rec::next` has not yet
been folded into a declaration.

```text
clang-query> match varDecl(hasType(templateSpecializationType(hasAnyTemplateArgument(
                 isExpr(hasDescendant(declRefExpr(to(fieldDecl(hasName("next"))))))))))
```

**Expected:** 1 match — `Chain<&Rec::next> chain` at `trav_types.cpp:125`.

## 10.7 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| `hasType` Decl vs QualType form | `hasType(cxxRecordDecl(…))` is `hasDeclaration` in disguise and stops at a typedef |
| Sugar vs canonical | `hasCanonicalType` / `hasUnqualifiedDesugaredType` see through `XAlias` and `int_ref` |
| `hasDeclaration` | One matcher walks 17 node kinds back to their declaration |
| One-level type steps | `pointee`, `pointsTo`, `references`, `hasElementType`, `innerType`, `hasDecayedType`, … |
| TypeLoc vs QualType | `hasTypeLoc(loc(…))` follows the declarator syntax; `loc` bridges back |
| Written vs resolved template args | `…ArgumentLoc` needs something spelled; `hasTemplateArgument` sees implicit instantiations |
| Nested-name specifiers | `A::B::` → `hasPrefix` → `A::`; `specifiesType` / `specifiesNamespace` |

**Quiz.** Find every variable whose *written* type is a template specialization whose
first template argument is `int` — using the type route, not the specialization-decl
route.

> [!hint]- Hint
> `varDecl(hasType(templateSpecializationType(…)))` gets you to the written type; inside it, `hasTemplateArgument(0, …)` with `refersToType(asString("int"))` picks argument zero.

> [!success]- Answer
> `varDecl(hasType(templateSpecializationType(hasTemplateArgument(0, refersToType(asString("int"))))))` — 4 matches: `wrapped` (line 44), `pid` (line 110), `vi` (line 113), `mat` (line 119).

---

[← Part 9 — Traversal Matchers II — Statements & Expressions](part_9_traversal_stmts.md) | [Part 11 — Objective-C, OpenMP, CUDA & Blocks →](part_11_objc_openmp_cuda_blocks.md)
