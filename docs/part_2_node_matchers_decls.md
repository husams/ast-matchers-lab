# Part 2 — Node Matchers I — Declarations

[← Part 1 — clang-query & the DSL Grammar](part_1_clang_query_and_the_dsl.md) | [Part 3 — Node Matchers II — Statements & Expressions →](part_3_node_matchers_stmts.md)

**Sample:** `manifests/decls.cpp` · flags: `-std=c++23`

## What You'll Learn
- What a *node matcher* is, and why it is the only kind of matcher that can sit at the outermost position of a `match` command.
- The spelling rule that turns any Clang AST class name into its node matcher (`CXXRecordDecl` → `cxxRecordDecl()`).
- The shape of Clang's `Decl` hierarchy, so you can pick the *narrowest* matcher for what you mean.
- Every declaration node matcher in the reference, run against one 127-line sample — plus the four non-`Decl` node kinds that live next to declarations: attributes, base specifiers, constructor initializers and lambda captures.
- Why a bare node matcher often reports more matches than you wrote in the file (implicit nodes), and the two knobs that tame it: `unless(isImplicit())` and `isExpansionInMainFile()`.

## The Big Picture

A **node matcher** names a *kind of AST node* and nothing else. `functionDecl()` means "any node that is a `FunctionDecl` (or a subclass of it)". On its own it says nothing about the node's name, its parent, or its children; everything else in the DSL (narrowing matchers such as `hasName`, traversal matchers such as `hasDeclContext`) is written *inside* the parentheses of a node matcher to refine it.

The spelling rule is mechanical: take the Clang class name, lower-case the leading run of capitals, and add `()`.

```text
  Clang class                       node matcher
  -----------                       ------------
  Decl                              decl()
  FunctionDecl                      functionDecl()
  CXXRecordDecl                     cxxRecordDecl()
  ClassTemplatePartialSpecializationDecl
                                    classTemplatePartialSpecializationDecl()
  CXXCtorInitializer                cxxCtorInitializer()
```

Node matchers are also the **only matchers allowed at the outermost position** of a `match` command. `match hasName("x")` is an error: clang-query needs to know which nodes to walk before it can ask a question about them. So every command in this lab starts with one of the matchers in Parts 2–4.

Because a node matcher matches a class *and all its subclasses*, the `Decl` hierarchy decides how wide a net you cast. A compact view of the part that matters here:

```text
Decl
├── TranslationUnitDecl                     translationUnitDecl()
├── AccessSpecDecl · StaticAssertDecl · FileScopeAsmDecl · FriendDecl
├── LinkageSpecDecl · ExportDecl · EmptyDecl
└── NamedDecl                               namedDecl()
    ├── NamespaceDecl · NamespaceAliasDecl · LabelDecl
    ├── UsingDirectiveDecl · UsingDecl · UsingEnumDecl · UsingShadowDecl
    ├── TemplateDecl
    │   ├── ClassTemplateDecl · FunctionTemplateDecl
    │   ├── TypeAliasTemplateDecl · TemplateTemplateParmDecl
    │   └── ConceptDecl
    ├── TypeDecl
    │   ├── TagDecl                         tagDecl()
    │   │   ├── EnumDecl
    │   │   └── RecordDecl                  recordDecl()
    │   │       └── CXXRecordDecl           cxxRecordDecl()
    │   │           └── ClassTemplateSpecializationDecl
    │   │               └── ClassTemplatePartialSpecializationDecl
    │   ├── TypedefNameDecl                 typedefNameDecl()
    │   │   ├── TypedefDecl · TypeAliasDecl
    │   ├── TemplateTypeParmDecl
    │   └── UnresolvedUsingTypenameDecl
    └── ValueDecl                           valueDecl()
        ├── EnumConstantDecl · IndirectFieldDecl · BindingDecl
        ├── UnresolvedUsingValueDecl
        └── DeclaratorDecl                  declaratorDecl()
            ├── FieldDecl
            ├── FunctionDecl                functionDecl()
            │   ├── CXXDeductionGuideDecl
            │   └── CXXMethodDecl           cxxMethodDecl()
            │       ├── CXXConstructorDecl · CXXDestructorDecl · CXXConversionDecl
            ├── NonTypeTemplateParmDecl
            └── VarDecl                     varDecl()
                ├── ParmVarDecl
                └── DecompositionDecl
```

Read it bottom-up when choosing a matcher: `cxxConstructorDecl()` is the tightest fit for "a constructor"; `cxxMethodDecl()` also catches destructors, conversions and plain methods; `functionDecl()` catches free functions too; `declaratorDecl()` adds fields and variables; `valueDecl()` adds enumerators; `namedDecl()` adds types and namespaces; `decl()` adds everything with no name at all.

Two facts about the AST will keep surprising you in this part:

1. **Clang synthesises nodes you never typed.** Implicit copy constructors, injected class names, deduction guides, the `std` namespace, a few dozen builtin `typedef`s, and so on. A bare `cxxRecordDecl()` on our 127-line sample reports over 40 matches. When an entry below wraps the node matcher in `unless(isImplicit())` (drop synthesised nodes) or `isExpansionInMainFile()` (drop nodes that have no location in our file), that is the only reason. Both are narrowing matchers you will meet properly in Part 5; here they are just a filter.
2. **Some nodes are not visited on their own.** `cxxBaseSpecifier()` and `lambdaCapture()` are rejected as top-level matchers, and `labelDecl()` is only reachable through the statement that owns it. Those entries show the shortest working spelling.

Where a bare node matcher would hit many nodes, the entries also scope it with `hasDeclContext(...)` ("declared directly inside …") or `hasAncestor(...)`; both are traversal matchers from Part 6. The prose of each entry always states what the *bare* form means.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/decls.cpp -- -std=c++23
```

Keep `manifests/decls.cpp` open beside it; every **Expected** line quotes its line numbers.

---

## 2.1 — The Root and the Generic Declaration Matchers

These matchers sit at the top of the hierarchy. They are rarely the final answer, but they are what you reach for when you do not yet know the exact node kind, or when you want "everything declared in scope X".

### `translationUnitDecl(Matcher<TranslationUnitDecl>...)` — Matcher<Decl>

The single root of the whole AST; every other declaration hangs below it. It has no source location, so the match prints no code. Its real use is as the *context* argument of other matchers: `hasDeclContext(translationUnitDecl())` means "declared at file scope".

```text
clang-query> match translationUnitDecl()
```

**Expected:** 1 match — the translation unit itself (no source line is shown; the root has no location).

### `decl(Matcher<Decl>...)` — Matcher<Decl>

The widest net: any declaration at all, named or not — functions, classes, friends, `static_assert`, access specifiers, the lot. Bare `decl()` on this sample reports a few hundred matches (most of them implicit), so scope it. Here: everything declared directly inside `namespace geo`.

```text
clang-query> match decl(hasDeclContext(namespaceDecl(hasName("geo"))))
```

**Expected:** 3 matches — `origin` (`decls.cpp:6`), `reset` (`decls.cpp:7`) and `struct Point` (`decls.cpp:8`).

### `namedDecl(Matcher<NamedDecl>...)` — Matcher<Decl>

Anything that *could* carry a name: types, functions, variables, namespaces, templates, enumerators — even an anonymous union (its name is just empty). Practically every `hasName(...)` query starts here when you do not care what kind of thing the name belongs to. Scoped to `namespace tags`, notice that a class template shows up **twice**: once as the `ClassTemplateDecl` and once as the `CXXRecordDecl` pattern it wraps.

```text
clang-query> match namedDecl(hasDeclContext(namespaceDecl(hasName("tags"))))
```

**Expected:** 7 matches — `X` (`decls.cpp:122`), the template `Z` and its templated class (both `decls.cpp:123`), `S` (`decls.cpp:124`), `U` (`decls.cpp:125`), `E` (`decls.cpp:126`) and `F` (`decls.cpp:127`).

### `valueDecl(Matcher<ValueDecl>...)` — Matcher<Decl>

Declarations that denote a *value* with a type: variables, fields, functions, enumerators, structured bindings, indirect fields. It is the split point between "things that are types" and "things that have types". Inside `namespace tags` that is the three enumerators and the function `F` — the types `X`, `Z`, `S`, `U`, `E` are excluded. (`hasAncestor` is used because the enumerators' declaration context is the enum, not the namespace.)

```text
clang-query> match valueDecl(hasAncestor(namespaceDecl(hasName("tags"))))
```

**Expected:** 4 matches — `A`, `B`, `C` (`decls.cpp:126`) and `F` (`decls.cpp:127`).

### `declaratorDecl(Matcher<DeclaratorDecl>...)` — Matcher<Decl>

A `ValueDecl` that was introduced by a *declarator* — a field, a variable, a function or a non-type template parameter. Enumerators and bindings are values but not declarators. Compare with the `decl(...)` example above: same scope, but `struct Point` drops out because a class is not a declarator.

```text
clang-query> match declaratorDecl(hasDeclContext(namespaceDecl(hasName("geo"))))
```

**Expected:** 2 matches — `origin` (`decls.cpp:6`) and `reset` (`decls.cpp:7`).

### `staticAssertDecl(Matcher<StaticAssertDecl>...)` — Matcher<Decl>

A `static_assert(...)` at namespace, class or block scope. It is a declaration with no name and no value — only `decl()` and this matcher can see it.

```text
clang-query> match staticAssertDecl()
```

**Expected:** 1 match — `static_assert(sizeof(int) == 4, ...)` at `decls.cpp:12`.

### `fileScopeAsmDecl(Matcher<FileScopeAsmDecl>...)` — Matcher<Decl>

A top-level `__asm("...")` declaration. An `asm` *statement* inside a function body is a different node (`asmStmt`, Part 3) and is not matched.

```text
clang-query> match fileScopeAsmDecl()
```

**Expected:** 1 match — `__asm("nop")` at `decls.cpp:13`.

## 2.2 — Functions, Parameters and Methods

The `FunctionDecl` family. Remember that in Clang every constructor, destructor, conversion function and method *is* a `FunctionDecl`, so `functionDecl()` alone casts a wide net; the specialised matchers narrow it by kind.

### `functionDecl(Matcher<FunctionDecl>...)` — Matcher<Decl>

Any function declaration or definition: free functions, methods, constructors, destructors, deduction guides, friend functions and the templated function inside a function template. Bare, it also returns every implicit special member Clang synthesised, so this example keeps only *definitions* whose declaration context is the file itself.

```text
clang-query> match functionDecl(isDefinition(), hasDeclContext(translationUnitDecl()))
```

**Expected:** 5 matches — `use_bindings` (`decls.cpp:49`), `twice` (`decls.cpp:64`), `alias_demo` (`decls.cpp:89`), `countdown` (`decls.cpp:104`) and `capture_demo` (`decls.cpp:114`).

### `parmVarDecl(Matcher<ParmVarDecl>...)` — Matcher<Decl>

A function parameter. Parameters are variables (`ParmVarDecl` derives from `VarDecl`), so they also answer to `varDecl()`; use this matcher when you mean *only* parameters. Scoped to one function with `hasAncestor`:

```text
clang-query> match parmVarDecl(hasAncestor(functionDecl(hasName("free_function"))))
```

**Expected:** 2 matches — `int count` and `double scale`, both on `decls.cpp:16`.

### `cxxMethodDecl(Matcher<CXXMethodDecl>...)` — Matcher<Decl>

Any member function of a class, including constructors, destructors and conversion functions (they all derive from `CXXMethodDecl`), and including out-of-line definitions. Bare, it also lists implicit copy/move members and the `operator()` of every lambda. Scoped to `Shape` and with implicit members dropped, you get the six members declared in the class plus the out-of-line definition of `area` — a redeclaration is its own node.

```text
clang-query> match cxxMethodDecl(ofClass(hasName("Shape")), unless(isImplicit()))
```

**Expected:** 7 matches — `Shape()` (`decls.cpp:20`), `Shape(int)` (`decls.cpp:21`), `~Shape()` (`decls.cpp:22`), `area` (`decls.cpp:23`), `operator bool` (`decls.cpp:24`), `corners` (`decls.cpp:25`) and the definition `Shape::area` (`decls.cpp:31`).

### `cxxConstructorDecl(Matcher<CXXConstructorDecl>...)` — Matcher<Decl>

A constructor. The bare form on this sample reports 14: two written for `Shape`, one for `Box`, and eleven implicit default/copy/move constructors Clang declared for `Shape`, `Circle`, `Square`, `Pair` and the `Grid` specialisation. Dropping the implicit ones leaves what you typed.

```text
clang-query> match cxxConstructorDecl(unless(isImplicit()))
```

**Expected:** 3 matches — `Shape()` (`decls.cpp:20`), `Shape(int)` (`decls.cpp:21`) and `Box(T)` (`decls.cpp:66`).

### `cxxDestructorDecl(Matcher<CXXDestructorDecl>...)` — Matcher<Decl>

A destructor. Only `Shape` declares one explicitly; `Circle`, `Square` and both lambda closure types received implicit destructors, which the filter removes.

```text
clang-query> match cxxDestructorDecl(unless(isImplicit()))
```

**Expected:** 1 match — `virtual ~Shape()` at `decls.cpp:22`.

### `cxxConversionDecl(Matcher<CXXConversionDecl>...)` — Matcher<Decl>

A user-defined conversion function, `operator T()`. Conversion *constructors* (`Shape(int)`) are not conversion decls; they are constructors.

```text
clang-query> match cxxConversionDecl()
```

**Expected:** 1 match — `operator bool() const` at `decls.cpp:24`.

### `cxxDeductionGuideDecl(Matcher<CXXDeductionGuideDecl>...)` — Matcher<Decl>

A class template argument deduction (CTAD) guide, `Box(int) -> Box<int>`. Clang also generates one implicit guide per constructor plus a copy-deduction candidate, so `Box` alone yields three:

```text
clang-query> match cxxDeductionGuideDecl()
```

**Expected:** 3 matches — the implicit guides from `Box(T)` and the copy candidate (both reported at `decls.cpp:66`) and the user-written guide at `decls.cpp:67`.

Keep only the one you wrote:

```text
clang-query> match cxxDeductionGuideDecl(unless(isImplicit()))
```

**Expected:** 1 match — `Box(int) -> Box<int>` at `decls.cpp:67`.

### `labelDecl(Matcher<LabelDecl>...)` — Matcher<Decl>

The declaration of a `goto` label (`again:`). A `LabelDecl` is never visited on its own by the matcher traversal — bare `labelDecl()` returns 0 on this file — but it is reachable from the `LabelStmt` that owns it via `hasDeclaration`.

```text
clang-query> match labelStmt(hasDeclaration(labelDecl()))
```

**Expected:** 1 match — the label `again:` at `decls.cpp:105`.

## 2.3 — Records, Fields and Friends

Classes, structs and unions are `RecordDecl`s; in C++ mode every one of them is actually the subclass `CXXRecordDecl`. Their members are `FieldDecl`s, and the odd corners — anonymous unions, access specifiers, friends, structured bindings — each have their own node.

### `tagDecl(Matcher<TagDecl>...)` — Matcher<Decl>

Anything introduced with a *tag* keyword: `class`, `struct`, `union` **and `enum`**. The bare form is inflated by injected-class-name records and template instantiations, so here it is scoped to `namespace tags`, which mirrors the reference example exactly.

```text
clang-query> match tagDecl(hasDeclContext(namespaceDecl(hasName("tags"))))
```

**Expected:** 5 matches — `X` (`decls.cpp:122`), `Z` (`decls.cpp:123`), `S` (`decls.cpp:124`), `U` (`decls.cpp:125`) and `E` (`decls.cpp:126`).

### `recordDecl(Matcher<RecordDecl>...)` — Matcher<Decl>

Class, struct and union declarations — enums drop out compared with `tagDecl()`. Forward declarations (`class X;`) count, and the templated class inside a class template counts once.

```text
clang-query> match recordDecl(hasDeclContext(namespaceDecl(hasName("tags"))))
```

**Expected:** 4 matches — `X` (`decls.cpp:122`), `Z` (`decls.cpp:123`), `S` (`decls.cpp:124`) and `U` (`decls.cpp:125`).

### `cxxRecordDecl(Matcher<CXXRecordDecl>...)` — Matcher<Decl>

The C++ record node, which is what you get for every `class`/`struct`/`union` in a C++ file — so in practice `recordDecl()` and `cxxRecordDecl()` match the same nodes here. Prefer `cxxRecordDecl()` because only it accepts C++-specific narrowers such as `isDerivedFrom` or `hasMethod` (Part 5).

```text
clang-query> match cxxRecordDecl(hasDeclContext(namespaceDecl(hasName("tags"))))
```

**Expected:** 4 matches — `X` (`decls.cpp:122`), `Z` (`decls.cpp:123`), `S` (`decls.cpp:124`) and `U` (`decls.cpp:125`).

### `fieldDecl(Matcher<FieldDecl>...)` — Matcher<Decl>

A non-static data member. Note that member variables are *not* `VarDecl`s in Clang; `varDecl()` never sees them. The bare form on this sample also reports the unnamed anonymous-union member of `Packet` and the closure fields lambdas create for their captures, so scope it:

```text
clang-query> match fieldDecl(hasDeclContext(recordDecl(hasName("Shape"))))
```

**Expected:** 2 matches — `sides_` (`decls.cpp:27`) and `name_` (`decls.cpp:28`).

### `indirectFieldDecl(Matcher<IndirectFieldDecl>...)` — Matcher<Decl>

The members of an anonymous union (or anonymous struct) as seen from the *enclosing* class. `Packet::code` is really `Packet::<anon>::code`; the indirect field is the alias that lets you write `pkt.code`.

```text
clang-query> match indirectFieldDecl()
```

**Expected:** 2 matches — `code` and `ratio`, both on `decls.cpp:38`.

### `accessSpecDecl(Matcher<AccessSpecDecl>...)` — Matcher<Decl>

A `public:`, `protected:` or `private:` label inside a class body. It is a declaration in its own right, with a location, which is why tools can rewrite it.

```text
clang-query> match accessSpecDecl()
```

**Expected:** 2 matches — `public:` (`decls.cpp:19`) and `private:` (`decls.cpp:26`) in `Shape`.

### `friendDecl(Matcher<FriendDecl>...)` — Matcher<Decl>

A `friend` declaration — of a function or of a class. The friend node *wraps* the function or type it befriends; the befriended function (`peek`) is a separate `FunctionDecl` whose semantic context is the enclosing namespace.

```text
clang-query> match friendDecl()
```

**Expected:** 2 matches — `friend void peek(const Vault&)` (`decls.cpp:43`) and `friend class Auditor` (`decls.cpp:44`).

### `decompositionDecl(Matcher<DecompositionDecl>...)` — Matcher<Decl>

The *whole* structured binding `auto [first, second] = p;`. It is a `VarDecl` (the hidden variable that holds the copy of `p`) with the individual bindings as children.

```text
clang-query> match decompositionDecl()
```

**Expected:** 1 match — `auto [first, second] = p` at `decls.cpp:51`.

### `bindingDecl(Matcher<BindingDecl>...)` — Matcher<Decl>

One name introduced by a structured binding. Bindings are `ValueDecl`s but not variables: `varDecl()` does not see `first` or `second`.

```text
clang-query> match bindingDecl()
```

**Expected:** 2 matches — `first` and `second`, both on `decls.cpp:51`.

## 2.4 — Templates and Concepts

A template is *two* nodes: the `TemplateDecl` that owns the parameter list, and the templated declaration (class, function, alias) it wraps. Specialisations, partial specialisations and instantiations are further separate nodes. Concepts are `TemplateDecl`s too.

### `classTemplateDecl(Matcher<ClassTemplateDecl>...)` — Matcher<Decl>

The `template<...> class` node itself — not its specialisations or instantiations. Every class template in the sample is explicit, so the bare form is safe.

```text
clang-query> match classTemplateDecl()
```

**Expected:** 5 matches — `Grid` (`decls.cpp:56`), `Box` (`decls.cpp:66`), `Bag` (`decls.cpp:69`), `Derived` (`decls.cpp:75`) and `tags::Z` (`decls.cpp:123`).

### `classTemplateSpecializationDecl(Matcher<ClassTemplateSpecializationDecl>...)` — Matcher<Decl>

A specialisation of a class template: explicit (`template<> class Grid<int,int,1>`), partial, **or implicit** (`Grid<char,char,2> grid;` instantiates one, reported at the primary template's line). Bare, it would also list the `Box<int>` named by the deduction guide, so scope by name:

```text
clang-query> match classTemplateSpecializationDecl(hasName("Grid"))
```

**Expected:** 3 matches — the implicit instantiation `Grid<char, char, 2>` (reported at `decls.cpp:56`), the partial specialisation (`decls.cpp:58`) and the explicit specialisation (`decls.cpp:60`).

### `classTemplatePartialSpecializationDecl(Matcher<ClassTemplatePartialSpecializationDecl>...)` — Matcher<Decl>

Only *partial* specialisations — the ones that still have template parameters. The full specialisation `Grid<int, int, 1>` does not match.

```text
clang-query> match classTemplatePartialSpecializationDecl()
```

**Expected:** 1 match — `class Grid<T, T*, I>` at `decls.cpp:58`.

### `functionTemplateDecl(Matcher<FunctionTemplateDecl>...)` — Matcher<Decl>

The `template<...>` wrapper around a function. Implicit deduction guides for `Box` are wrapped in implicit function templates too, so the bare form reports three:

```text
clang-query> match functionTemplateDecl()
```

**Expected:** 3 matches — `twice` (`decls.cpp:64`) and the two implicit deduction-guide templates for `Box` (`decls.cpp:66`).

The user-written guide `Box(int) -> Box<int>` has no template parameters of its own, so it is a plain `CXXDeductionGuideDecl`, not a template. Drop the implicit wrappers:

```text
clang-query> match functionTemplateDecl(unless(isImplicit()))
```

**Expected:** 1 match — `template <typename T> T twice(T v)` at `decls.cpp:64`.

### `templateTypeParmDecl(Matcher<TemplateTypeParmDecl>...)` — Matcher<Decl>

A *type* template parameter (`typename T` / `class T`). Scoped to `Bag`, this finds `Elem` **and** the unnamed `typename` inside the template template parameter `Container` — but not the non-type parameter `Cap`.

```text
clang-query> match templateTypeParmDecl(hasAncestor(classTemplateDecl(hasName("Bag"))))
```

**Expected:** 2 matches — the anonymous parameter of `template <typename> class Container` and `Elem`, both on `decls.cpp:69`.

### `nonTypeTemplateParmDecl(Matcher<NonTypeTemplateParmDecl>...)` — Matcher<Decl>

A *value* template parameter (`int N`). All three in the sample are explicit, so the bare form is exact.

```text
clang-query> match nonTypeTemplateParmDecl()
```

**Expected:** 3 matches — `I` of `Grid` (`decls.cpp:56`), `I` of the partial specialisation (`decls.cpp:58`) and `Cap` of `Bag` (`decls.cpp:69`).

### `templateTemplateParmDecl(Matcher<TemplateTemplateParmDecl>...)` — Matcher<Decl>

A template *template* parameter — a parameter that must itself be a template, such as `template <typename> class Container`.

```text
clang-query> match templateTemplateParmDecl()
```

**Expected:** 1 match — `Container` at `decls.cpp:69`.

### `conceptDecl(Matcher<ConceptDecl>...)` — Matcher<Decl>

A C++20 `concept` definition. Both concepts in the sample are found; their constraint expressions are children (`requiresExpr` is a Part 3 node).

```text
clang-query> match conceptDecl()
```

**Expected:** 2 matches — `Small` (`decls.cpp:72`) and `Dereferenceable` (`decls.cpp:73`).

### `requiresExprBodyDecl(Matcher<RequiresExprBodyDecl>...)` — Matcher<Decl>

The braces of a requires-expression, `requires(T p) { *p; }` — the `{ *p; }` part is a declaration context that owns the local parameter and requirements.

**Not in clang-query 22** — the matcher exists in the reference but is not registered in this clang-query build (`Matcher not found: requiresExprBodyDecl`). The closest working query is the concept that owns the requires-expression:

```text
clang-query> match conceptDecl(hasName("Dereferenceable"))
```

**Expected:** 1 match — `concept Dereferenceable = requires(T p) { *p; }` at `decls.cpp:73`.

### `unresolvedUsingTypenameDecl(Matcher<UnresolvedUsingTypenameDecl>...)` — Matcher<Decl>

A `using typename Base::value_type;` inside a template, where `Base` is a dependent type and so the name cannot be resolved until instantiation.

```text
clang-query> match unresolvedUsingTypenameDecl()
```

**Expected:** 1 match — `using typename Base::value_type` at `decls.cpp:77`.

### `unresolvedUsingValueDecl(Matcher<UnresolvedUsingValueDecl>...)` — Matcher<Decl>

The value-flavoured twin: `using Base::size;` inside a template. Once `Base` is known it would become an ordinary `UsingDecl`; while dependent, it is this node.

```text
clang-query> match unresolvedUsingValueDecl()
```

**Expected:** 1 match — `using Base::size` at `decls.cpp:78`.

## 2.5 — Enums, Aliases and the `using` Family

Three ways to name a type (`typedef`, `using`, alias template), two kinds of enum, and the five distinct `using` nodes that C++ has grown over the years.

### `enumDecl(Matcher<EnumDecl>...)` — Matcher<Decl>

An `enum` or `enum class` declaration. It is a `TagDecl` but *not* a `RecordDecl`.

```text
clang-query> match enumDecl()
```

**Expected:** 3 matches — `Color` (`decls.cpp:82`), `Mode` (`decls.cpp:83`) and `tags::E` (`decls.cpp:126`).

### `enumConstantDecl(Matcher<EnumConstantDecl>...)` — Matcher<Decl>

One enumerator. Enumerators are `ValueDecl`s whose declaration context is the enum.

```text
clang-query> match enumConstantDecl()
```

**Expected:** 8 matches — `Red`, `Green`, `Blue` (`decls.cpp:82`), `Fast`, `Safe` (`decls.cpp:83`) and `A`, `B`, `C` (`decls.cpp:126`).

### `typedefNameDecl(Matcher<TypedefNameDecl>...)` — Matcher<Decl>

The common parent of `typedef` and `using` aliases — use it when you do not care which spelling was used. Clang predeclares dozens of builtin typedefs with no source location (`__builtin_va_list`, the SVE vector types on Apple silicon, …), which is why this example keeps only nodes from our file.

```text
clang-query> match typedefNameDecl(isExpansionInMainFile())
```

**Expected:** 3 matches — `typedef int Integer` (`decls.cpp:11`), `using Real = double` (`decls.cpp:85`) and the templated alias `Ptr` (`decls.cpp:86`).

### `typedefDecl(Matcher<TypedefDecl>...)` — Matcher<Decl>

Only the old-style `typedef`. Same builtin noise as above, same filter.

```text
clang-query> match typedefDecl(isExpansionInMainFile())
```

**Expected:** 1 match — `typedef int Integer` at `decls.cpp:11`.

### `typeAliasDecl(Matcher<TypeAliasDecl>...)` — Matcher<Decl>

Only `using Name = Type;`. The alias inside an alias template is a `TypeAliasDecl` too, so `Ptr` contributes one.

```text
clang-query> match typeAliasDecl()
```

**Expected:** 2 matches — `using Real = double` (`decls.cpp:85`) and `using Ptr = T*` (`decls.cpp:86`).

### `typeAliasTemplateDecl(Matcher<TypeAliasTemplateDecl>...)` — Matcher<Decl>

The `template<...>` wrapper around a `using` alias.

```text
clang-query> match typeAliasTemplateDecl()
```

**Expected:** 1 match — `template <typename T> using Ptr = T*` at `decls.cpp:86`.

### `usingDecl(Matcher<UsingDecl>...)` — Matcher<Decl>

A using-*declaration*, `using geo::origin;` — brings one name into scope. (Not a using-directive, not an alias.)

```text
clang-query> match usingDecl()
```

**Expected:** 1 match — `using geo::origin` at `decls.cpp:88`.

### `usingShadowDecl(Matcher<UsingShadowDecl>...)` — Matcher<Decl>

The hidden node a using-declaration creates *per name it introduces*: it "shadows" the target so lookups in the new scope find it. `using geo::origin` makes one; `using enum Mode` makes one per enumerator.

```text
clang-query> match usingShadowDecl()
```

**Expected:** 3 matches — the shadow of `origin` (`decls.cpp:88`) and the shadows of `Fast` and `Safe` created by `using enum Mode` (both reported at `decls.cpp:91`).

### `usingDirectiveDecl(Matcher<UsingDirectiveDecl>...)` — Matcher<Decl>

A `using namespace X;` directive. Clang inserts an *implicit* using-directive for every unnamed namespace (that is how `namespace {}` members become visible), so the bare form reports two on this file; filter it.

```text
clang-query> match usingDirectiveDecl(unless(isImplicit()))
```

**Expected:** 1 match — `using namespace geo` at `decls.cpp:90`.

### `usingEnumDecl(Matcher<UsingEnumDecl>...)` — Matcher<Decl>

A C++20 `using enum E;` declaration.

```text
clang-query> match usingEnumDecl()
```

**Expected:** 1 match — `using enum Mode` at `decls.cpp:91`.

## 2.6 — Namespaces, Linkage and Variables

The remaining named-scope nodes, plus `varDecl()`, which is the workhorse of most real queries.

### `namespaceDecl(Matcher<NamespaceDecl>...)` — Matcher<Decl>

A `namespace` (named or anonymous). Clang also predeclares an implicit `namespace std`, which the bare form would report as a fourth, location-less match.

```text
clang-query> match namespaceDecl(unless(isImplicit()))
```

**Expected:** 3 matches — `geo` (`decls.cpp:5`), the anonymous namespace (`decls.cpp:97`) and `tags` (`decls.cpp:121`).

### `namespaceAliasDecl(Matcher<NamespaceAliasDecl>...)` — Matcher<Decl>

`namespace g = geo;` — an alias, not a namespace; `namespaceDecl()` does not match it.

```text
clang-query> match namespaceAliasDecl()
```

**Expected:** 1 match — `namespace g = geo` at `decls.cpp:98`.

### `linkageSpecDecl(Matcher<LinkageSpecDecl>...)` — Matcher<Decl>

An `extern "C"` (or `extern "C++"`) specification, whether braced or applied to a single declaration.

```text
clang-query> match linkageSpecDecl()
```

**Expected:** 2 matches — `extern "C" { ... }` (`decls.cpp:99`) and `extern "C" int c_var` (`decls.cpp:102`).

### `exportDecl(Matcher<ExportDecl>...)` — Matcher<Decl>

An `export` declaration in a C++20 module interface unit — a single exported declaration, a braced `export { ... }` block, or an exported namespace. `export` is only legal in a module unit, so this entry uses a second sample, `manifests/decls_module.cppm`; clang-query parses it with the same flags (the `.cppm` suffix tells Clang it is a module interface).

```text
# sample: manifests/decls_module.cppm -std=c++23
clang-query> match exportDecl()
```

**Expected:** 3 matches — `export void foo()` (`decls_module.cppm:5`), `export { int v; }` (`decls_module.cppm:6`) and `export namespace detail { ... }` (`decls_module.cppm:7`).

### `varDecl(Matcher<VarDecl>...)` — Matcher<Decl>

A variable: globals, locals, parameters, the hidden variable behind a structured binding, and the variable a lambda init-capture creates. It does **not** match class members (those are `fieldDecl()`). Bare, it reports every parameter of every implicit member too, so this example keeps globals only.

```text
clang-query> match varDecl(hasGlobalStorage())
```

**Expected:** 3 matches — `geo::origin` (`decls.cpp:6`), `grid` (`decls.cpp:62`) and `c_var` (`decls.cpp:102`).

## 2.7 — Non-`Decl` Nodes That Live Beside Declarations

Four node kinds are neither `Decl` nor `Stmt` but hang off declarations: an attribute on a declaration, a base in a class head, a member initialiser in a constructor, and a capture in a lambda. Two of them (`cxxBaseSpecifier`, `lambdaCapture`) are rejected as top-level matchers — clang-query says "Not a valid top-level matcher" — and must be reached through their owner. The remaining non-`Decl` node kinds (`qualType`, `typeLoc`, `nestedNameSpecifier`, `templateArgument`, `templateName`, …) are Part 4.

### `attr(Matcher<Attr>...)` — Matcher<Attr>

An attribute in any syntax: `[[nodiscard]]`, GNU `__attribute__((nonnull))`, MSVC `__declspec`, or a `#pragma`. Attributes can also be implicit (Clang attaches some to nodes it synthesises); the bare form reports 25 on this file, so filter:

```text
clang-query> match attr(unless(isImplicit()))
```

**Expected:** 3 matches — `[[nodiscard]]` on `corners` (`decls.cpp:25`), `[[nodiscard]]` on `Result` (`decls.cpp:111`) and `__attribute__((nonnull))` on `take`'s parameter (`decls.cpp:112`).

### `cxxBaseSpecifier(Matcher<CXXBaseSpecifier>...)` — Matcher<CXXBaseSpecifier>

One entry of a class's base list, such as `public virtual Shape`. It is not a top-level matcher; ask the class for its bases with `hasAnyBase` (or `hasDirectBase`, Part 6). The match reported is the *class*, once per class with at least one base.

```text
clang-query> match cxxRecordDecl(hasAnyBase(cxxBaseSpecifier()))
```

**Expected:** 3 matches — `Circle` (`decls.cpp:34`), `Square` (`decls.cpp:35`) and `Derived` (`decls.cpp:75`).

### `cxxCtorInitializer(Matcher<CXXCtorInitializer>...)` — Matcher<CXXCtorInitializer>

One member (or base) initialiser in a constructor's `: a(1), b(2)` list. This one *is* a top-level matcher. Implicit copy/move constructors carry implicit initialisers, so `isWritten()` keeps the ones you typed.

```text
clang-query> match cxxCtorInitializer(isWritten())
```

**Expected:** 3 matches — `sides_(0)` (`decls.cpp:20`), `sides_(sides)` and `name_("shape")` (both `decls.cpp:21`).

### `lambdaCapture(Matcher<LambdaCapture>...)` — Matcher<LambdaCapture>

One capture in a lambda's `[...]` — by copy, by reference, `this`, or an init-capture like `y = x`. Not a top-level matcher; reach it through `lambdaExpr(hasAnyCapture(...))` (Part 6). One match per lambda that has any capture:

```text
clang-query> match lambdaExpr(hasAnyCapture(lambdaCapture()))
```

**Expected:** 2 matches — `[x]` (`decls.cpp:116`) and `[y = x]` (`decls.cpp:117`).

## 2.8 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Spelling rule | `ClassTemplatePartialSpecializationDecl` → `classTemplatePartialSpecializationDecl()`; every class name maps mechanically. |
| Hierarchy = width | `decl()` ⊃ `namedDecl()` ⊃ `valueDecl()` ⊃ `declaratorDecl()` ⊃ `functionDecl()` ⊃ `cxxMethodDecl()` ⊃ `cxxConstructorDecl()`. |
| Implicit nodes | Clang adds special members, deduction guides, `namespace std`, builtin typedefs, using-directives for anonymous namespaces; `unless(isImplicit())` and `isExpansionInMainFile()` remove them. |
| Two nodes per template | A class template is a `ClassTemplateDecl` *and* a `CXXRecordDecl`; `namedDecl` counted `Z` twice. |
| Redeclarations are nodes | `Shape::area` at line 31 matched `cxxMethodDecl` separately from its in-class declaration. |
| Not everything is top-level | `cxxBaseSpecifier`, `lambdaCapture` need an owner; `labelDecl` is reachable only via `labelStmt`. |
| Fields vs variables | `fieldDecl()` for members, `varDecl()` for everything else; bindings and enumerators are neither. |

**Quiz.** How many constructors *written in the file* have at least one member initialiser you typed? Combine a node matcher from 2.2 with the initializer matcher from 2.7 (and the `hasAnyConstructorInitializer` traversal from Part 6).

> [!hint]- Hint
> Start from `cxxConstructorDecl(...)`, drop implicit ones, and require an initialiser that `isWritten()`.

> [!success]- Answer
> `cxxConstructorDecl(unless(isImplicit()), hasAnyConstructorInitializer(cxxCtorInitializer(isWritten())))` — 2 matches: `Shape()` at `decls.cpp:20` and `Shape(int)` at `decls.cpp:21`. `Box(T)` is only declared, so it has no initialisers.

---

[← Part 1 — clang-query & the DSL Grammar](part_1_clang_query_and_the_dsl.md) | [Part 3 — Node Matchers II — Statements & Expressions →](part_3_node_matchers_stmts.md)
