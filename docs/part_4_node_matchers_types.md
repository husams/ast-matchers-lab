# Part 4 — Node Matchers III — Types & TypeLocs

[← Part 3 — Node Matchers II — Statements & Expressions](part_3_node_matchers_stmts.md) | [Part 5 — Narrowing Matchers I — Logic & Declarations →](part_5_narrowing_logic_decls.md)

**Sample:** `manifests/types.cpp` · flags: `-std=c++23`

## What You'll Learn
- The three faces of a type in Clang: `Type` (the thing), `QualType` (the thing plus `const`/`volatile`), `TypeLoc` (where it is written).
- Why type node matchers are usually reached through `hasType(...)` / `hasTypeLoc(...)`, and what happens when you use them as the outermost matcher instead.
- How to count builtin, pointer, reference, member-pointer and array types; function types; records, enums and tags.
- How "sugar" nodes (`typedef`, `using`, parentheses, decay, attribute macros) wrap the canonical type.
- How templates show up in types: specializations, type parameters, substituted parameters, injected class names, CTAD, dependent names.
- `auto`, `decltype`, `__underlying_type`, `_Atomic`, `_Complex`.
- TypeLocs, nested name specifiers (`a::b::`), template arguments and template names.

## The Big Picture

Every declaration in the AST carries a type, but Clang stores that type in three layers:

```
   int  const  * const  p;            <-- what you wrote
        |             |
   TypeLoc  ------------------  "where it is written" — has a source range
        |
   QualType = { Type*, const/volatile/restrict bits }
        |
   Type   ---  the node kind: PointerType, BuiltinType, RecordType, ...
        |
   canonical Type  --  same thing with every typedef / using / paren
                       / attribute-macro peeled off ("desugared")
```

* A **`Type`** is a unique, immutable node in the `ASTContext`. `int`, `int *`, `Box<char, 2>` each exist once. A `Type` has **no location**: it is not written anywhere in particular, it just *is*.
* A **`QualType`** is a `Type` pointer plus the cv-qualifier bits. `const int` is `QualType{ BuiltinType(int), const }`. Almost every "type of X" accessor in Clang returns a `QualType`, which is why `hasType(...)` accepts both `Matcher<QualType>` and `Matcher<Type>`.
* A **`TypeLoc`** is a `Type` together with the source range where it was spelled. TypeLocs are what clang-query can show you with a caret. A `Type` match, by contrast, prints **no location** (only `Binding for "root":` followed by the type text, or nothing at all in `diag` output mode).
* **Sugar** is the difference between what you wrote and what the compiler means. `Int ti` has the sugared type `TypedefType(Int)` whose canonical type is `BuiltinType(int)`. Type matchers see the *sugared* node unless you desugar with `hasUnqualifiedDesugaredType(...)` / `hasCanonicalType(...)` (Part 7).

**Type node matchers are usually not the outermost matcher.** The natural question is "which *variables* have type X?", and that is `varDecl(hasType(pointerType()))`. `hasType` takes the `QualType` of the declaration and feeds its `Type` to your matcher. Still, clang-query lets any node matcher stand alone, and `match pointerType()` is a fine way to *count* the pointer types in a file, so this part shows both forms: the standalone `match xxxType()` and the nested `varDecl(hasType(xxxType()))`.

Two things bite when a type matcher is outermost:

1. **Traversal order visits every written type, plus the implicit ones.** In the default `AsIs` traversal the visitor also walks the compiler-provided declarations (`__int128`, `__NSConstantString_tag`, and on Apple Silicon ~90 SVE/NEON vector typedefs) and every implicitly declared copy constructor and instantiation. `match builtinType()` in `AsIs` mode gives ~150 matches on this Mac and a different number on an x86 Mac. Every standalone example below therefore begins with `set traversal IgnoreUnlessSpelledInSource`, which skips implicit nodes and makes the counts stable and explainable. (Part 1 introduced `set traversal`; Part 12 revisits it.)
2. **The outermost `qualType(...)` visits null types.** Deduced `auto` declarations expose a `NULL TYPE` `QualType` during traversal, and a narrowing matcher such as `qualType(isConstQualified())` at the top level **crashes clang-query 22** with a stack trace. Keep `qualType(...)` nested (`varDecl(hasType(qualType(...)))`), where the declaration guarantees a real type.

Because a `Type` has no location, use `set output print` to see the type text, or `set output dump` to see the sugar chain. `hasTypeLoc(...)` + `.bind` gives you a caret at the exact characters.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/types.cpp -- -std=c++23
```

---

## 4.1 — The Three Roots: `type`, `qualType`, `typeLoc`

These three accept any node of their kind. Alone they are only useful for counting; their job is to hold narrowing matchers (`qualType(isConstQualified())`) or a `.bind` so a later `set print-matcher` / `dump` can show you the node.

### `type(Matcher<Type>...)` — Matcher<Type>

Matches any `Type` node. Standalone it visits every written type in the file, including the nested pieces (`int` inside `int *`, `A` inside `int A::*`). Nested under `varDecl(hasType(...))` it gives you the declared type of a variable as a bindable node.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match type()
```

**Expected:** 134 matches — every type spelled in `types.cpp`, one match per spelling, no locations printed.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasName("p"), hasType(type().bind("t")))
```

**Expected:** 1 match — `int *p` at `types.cpp:9`. Only `root` gets a caret; the `t` binding is a `Type` and prints no location.

### `qualType(Matcher<QualType>...)` — Matcher<QualType>

Matches a `QualType`: a `Type` plus its `const`/`volatile` bits. Qualifier narrowing matchers (`isConstQualified()`, `isVolatileQualified()`, Part 7) only work here, never on `type()`. Keep it nested: at the top level it meets null types and crashes (see the Big Picture).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(qualType(isConstQualified())))
```

**Expected:** 1 match — `const int ci = 0` at `types.cpp:93`.

```clang-query
set output dump
match varDecl(hasName("ti"), hasType(qualType().bind("q")))
```

**Expected:** 1 match — `Int ti = 5` at `types.cpp:43`; the dump of `q` shows `TypedefType 'Int' sugar` over `BuiltinType 'int'`.

### `typeLoc(Matcher<TypeLoc>...)` — Matcher<TypeLoc>

Matches any `TypeLoc`: a written type with a source range. This is the node kind that prints with a caret. `hasTypeLoc(...)` (on `varDecl`, `fieldDecl`, `functionDecl`, ...) is the usual way in; `loc(qualType(...))` (Part 8) converts a type matcher into a TypeLoc matcher.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match typeLoc()
```

**Expected:** 122 matches — every written type, each with its own `types.cpp:LINE:COL` location.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasName("p"), hasTypeLoc(typeLoc().bind("tl")))
```

**Expected:** 1 match — `int *p` at `types.cpp:9`; the `tl` binding gets its own caret under `int   *`, stopping before the name.

---

## 4.2 — Builtin Types, Pointers, References

The scalar layer: `int`/`float`/`bool`/`void` are `BuiltinType`s; `T *`, `T &`, `T &&` and `T C::*` wrap another type.

### `builtinType(Matcher<BuiltinType>...)` — Matcher<Type>

Matches the fundamental types (`int`, `float`, `bool`, `char`, `void`, ...). Note that `void` in `void ()` counts too. In `AsIs` mode this also reports the target's builtin typedef table (~150 matches on Apple Silicon), which is why the example switches traversal first.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match builtinType()
```

**Expected:** 43 matches — every `int`, `float`, `bool`, `char` and `void` spelled in the file (including return types and parameter types).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(builtinType()))
```

**Expected:** 7 matches — `i`, `f`, `b` (lines 6–8), the two unnamed `int` parameters of `fp` (line 30) and `h` (line 32), `k` (line 76) and `ci` (line 93). `Int ti` and `auto n` do **not** match: their sugared types are `TypedefType` and `AutoType`.

### `pointerType(Matcher<PointerType>...)` — Matcher<Type>

Matches `T *` for any `T` (but not Objective-C object pointers or member pointers). `pointee(...)` (Part 8) descends into `T`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match pointerType()
```

**Expected:** 6 matches — `int *` (`p`, line 9), `int (*)(int)` (`fp`, line 30), `int (*)[4]` (line 47), `int *` inside `int *[4]` (line 48), and the two function-pointer typedefs `X`/`Y` (lines 50–51).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(pointerType(pointee(builtinType()))))
```

**Expected:** 1 match — `int *p = &i` at `types.cpp:9`.

### `lValueReferenceType(Matcher<LValueReferenceType>...)` — Matcher<Type>

Matches `T &`. Standalone it sees the *written* `int &` and `auto &`; nested under `varDecl(hasType(...))` it sees the *deduced* types, so `auto &&fr = rr` (collapsed to `int &`) appears too.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match lValueReferenceType()
```

**Expected:** 2 matches — `int &` (line 10) and `auto &` (line 12).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(lValueReferenceType()))
```

**Expected:** 3 matches — `lr` (line 10), `ar` (line 12) and `fr` (line 13, `auto &&` collapsed to `int &`).

### `rValueReferenceType(Matcher<RValueReferenceType>...)` — Matcher<Type>

Matches `T &&`. Written form: three `&&` in the file. Deduced form: only `rr` and `xr`, because `fr` collapsed to an lvalue reference.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match rValueReferenceType()
```

**Expected:** 3 matches — `int &&` (line 11), `auto &&` (lines 13 and 14).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(rValueReferenceType()))
```

**Expected:** 2 matches — `rr` (line 11) and `xr` (line 14).

### `referenceType(Matcher<ReferenceType>...)` — Matcher<Type>

Matches both reference kinds at once.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match referenceType()
```

**Expected:** 5 matches — the five `&`/`&&` declarators on lines 10–14.

### `memberPointerType(Matcher<MemberPointerType>...)` — Matcher<Type>

Matches pointers to members, `T C::*`, whether the member is data or a function.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match memberPointerType()
```

**Expected:** 2 matches — `int A::*` (line 18) and `void (A::*)()` (line 19).

---

## 4.3 — Arrays

C++ has four array flavours and Clang gives each its own `Type` subclass. `arrayType()` covers all of them; the specific matchers pick one. Remember: an array *parameter* is not an array at all, it decays to a pointer.

### `arrayType(Matcher<ArrayType>...)` — Matcher<Type>

Matches every kind of array: constant-size, incomplete, variable-length and dependent-sized.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match arrayType()
```

**Expected:** 8 matches — `int[2]` (line 22), `int[]` (lines 23 and 24), `int[ia[0]]` (line 25), `int[4]` (line 47), `int *[4]` (line 48), `T[Size]` (line 64) and `int[3]` (the explicitly instantiated `data` member, line 69).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(arrayType()))
```

**Expected:** 4 matches — `ca`, `ia`, `va` and `array_of_ptrs`. `param` is missing: its type is a `DecayedType`, and `ptr_to_array` is a pointer.

### `constantArrayType(Matcher<ConstantArrayType>...)` — Matcher<Type>

Matches arrays whose size is an integer constant expression. `int ia[] = {2, 3}` *becomes* a `ConstantArrayType` (`int[2]`) once the initializer fixes the size, so it matches through `hasType` but not as a written `int[]`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match constantArrayType()
```

**Expected:** 4 matches — `int[2]` (line 22), `int[4]` (line 47), `int *[4]` (line 48), `int[3]` (line 69).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(constantArrayType(hasSize(4))))
```

**Expected:** 1 match — `int *array_of_ptrs[4]` at `types.cpp:48`.

### `incompleteArrayType(Matcher<IncompleteArrayType>...)` — Matcher<Type>

Matches `T[]` with no size. Only the *written* forms match: as a declared type, `ia` is completed by its initializer and `param` decays to `int *`, so `varDecl(hasType(incompleteArrayType()))` finds nothing. Go through the TypeLoc instead.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match incompleteArrayType()
```

**Expected:** 2 matches — `int[]` written for `ia` (line 23) and for `param` (line 24).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match declaratorDecl(hasTypeLoc(loc(incompleteArrayType())))
```

**Expected:** 2 matches — `int ia[] = {2, 3}` (line 23) and `int param[]` (line 24).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(incompleteArrayType()))
```

**Expected:** 0 matches — the declared types are `int[2]` and `int *`; the incomplete array only exists in the spelling.

### `variableArrayType(Matcher<VariableArrayType>...)` — Matcher<Type>

Matches C99-style VLAs, `int va[n]` where `n` is not a constant expression. The sample silences Clang's C++ extension warning with a pragma so the parse stays clean.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match variableArrayType()
```

**Expected:** 1 match — `int[ia[0]]` (`va`, line 25).

### `dependentSizedArrayType(Matcher<DependentSizedArrayType>...)` — Matcher<Type>

Matches arrays inside templates whose size depends on a template parameter (`T data[Size]`). After instantiation the same member becomes a `ConstantArrayType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match fieldDecl(hasType(dependentSizedArrayType()))
```

**Expected:** 1 match — `T data[Size]` at `types.cpp:64`.

### `dependentSizedExtVectorType(Matcher<DependentSizedExtVectorType>...)` — Matcher<Type>

Matches Clang's `__attribute__((ext_vector_type(N)))` vector type when the element type or `N` is dependent. In `Box<T, Size>` the `vec` typedef has both dependent.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match dependentSizedExtVectorType()
```

**Expected:** 1 match — `T __attribute__((ext_vector_type(Size)))` (line 65).

### `decayedType(Matcher<DecayedType>...)` — Matcher<Type>

Matches the adjusted type Clang gives an array (or function) parameter: `int param[]` is really `int *`, and `DecayedType` records both the original and the decayed type (`hasDecayedType(...)`, Part 8). A `DecayedType` is never *written*, so it is never visited standalone; you reach it through `hasType`, on the parameter or on any expression that names it.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match parmVarDecl(hasType(decayedType(hasDecayedType(pointerType()))))
```

**Expected:** 1 match — `int param[]` at `types.cpp:24`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match expr(hasType(decayedType(hasDecayedType(pointerType()))))
```

**Expected:** 1 match — the `param` reference in `param[1] = 0` at `types.cpp:26`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match decayedType()
```

**Expected:** 0 matches — nothing spells a decayed type, so the traversal never visits one.

---

## 4.4 — Function Types

A function declaration, a function pointer and a function typedef all carry a `FunctionType`. In C++ every one of them has a prototype, so `functionProtoType()` and `functionType()` agree; the difference only shows in C, where `void g()` has no prototype.

### `functionType(Matcher<FunctionType>...)` — Matcher<Type>

Matches any function type, `R (Params)`. Note that a function *pointer* variable's own type is a `PointerType`; the function type is its pointee, usually behind a `ParenType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match functionType()
```

**Expected:** 16 matches — every function declaration's type (`method`, `arrays`, `g`, `h`, `take`, `takeSpec`, `F`, `callF`, `Ctad(T)`, `Q::f` twice, `call`) plus the function types inside `fp`, `mfp`, `X` and `Y`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(pointsTo(ignoringParens(functionType()))))
```

**Expected:** 1 match — `int (*fp)(int)` at `types.cpp:30`. Without `ignoringParens` the pointee is the `ParenType` and nothing matches.

### `functionProtoType(Matcher<FunctionProtoType>...)` — Matcher<Type>

Matches function types that carry a parameter list — in C++ that is all of them. Narrowers such as `parameterCountIs(N)` (Part 6) live on this node.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match functionProtoType()
```

**Expected:** 16 matches — the same set as `functionType()`; C++ has no non-prototype functions.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match functionDecl(hasType(functionProtoType(parameterCountIs(1))))
```

**Expected:** 6 matches — `arrays`, `h`, `take`, `takeSpec`, `F` and the constructor `Ctad(T)`.

---

## 4.5 — Records, Enums, Tags

A *tag* is anything introduced with `struct`, `class`, `union` or `enum`. `tagType()` covers both `recordType()` and `enumType()`.

### `recordType(Matcher<RecordType>...)` — Matcher<Type>

Matches the type of a `struct`/`class`/`union`. Standalone it also counts the `A` inside `int A::*` and the `Q` inside `Q::f`; `T ut` does **not** appear, because its sugared type is a `UsingType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match recordType()
```

**Expected:** 9 matches — `A` ×4 (lines 18–19), `S` and `C` (line 39), `Q` ×2 (lines 89–90) and `nn::Q` (line 92).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(recordType()))
```

**Expected:** 3 matches — `S s`, `C c` (line 39) and `nn::Q q` (line 92).

### `enumType(Matcher<EnumType>...)` — Matcher<Type>

Matches the type of an `enum` or `enum class`. Combine with `hasDeclaration(enumDecl(isScoped()))` to tell them apart.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match enumType()
```

**Expected:** 3 matches — `E` and `SC` (line 39) and the `E` inside `__underlying_type(E)` (line 56).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(enumType(hasDeclaration(enumDecl(isScoped())))))
```

**Expected:** 1 match — `SC sc` at `types.cpp:39`.

### `tagType(Matcher<TagType>...)` — Matcher<Type>

Matches record and enum types together. The injected class name `Box<T, Size>` (line 66) is a tag type too.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match tagType()
```

**Expected:** 13 matches — the 9 record types, the 3 enum types and `Box<T, Size>` in `take(Box b)`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(tagType()))
```

**Expected:** 6 matches — `s`, `c`, `e`, `sc` (line 39), the parameter `Box<T, Size> b` of `take` (line 66) and `q` (line 92).

---

## 4.6 — Sugar: typedef, using, parentheses, macros

Sugar nodes keep the *spelling* the programmer chose. They sit on top of the canonical type and are what `hasType` sees first.

### `typedefType(Matcher<TypedefType>...)` — Matcher<Type>

Matches a use of a `typedef` name (`Int ti`). The declaration `typedef int Int` itself is a `typedefDecl`, not a type use.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match typedefType()
```

**Expected:** 1 match — `Int` in `Int ti = 5` (line 43).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(typedefType(hasDeclaration(typedefDecl(hasName("Int"))))))
```

**Expected:** 1 match — `Int ti = 5` at `types.cpp:43`.

### `usingType(Matcher<UsingType>...)` — Matcher<Type>

Matches a type named through a `using` declaration (`using lib::T; T ut;`). `throughUsingDecl(...)` (Part 8) reaches the shadow declaration.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match usingType()
```

**Expected:** 1 match — `T` in `T ut` (line 46).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(hasUnqualifiedDesugaredType(
  recordType(hasDeclaration(recordDecl(hasName("T")))))))
```

**Expected:** 1 match — `T ut` at `types.cpp:46`; desugaring peels the `UsingType` off and exposes `lib::T`.

### `parenType(Matcher<ParenType>...)` — Matcher<Type>

Matches the parentheses in declarators such as `int (*fp)(int)` and `int (*ptr_to_array)[4]`. The variable's own type is the pointer; the `ParenType` is its pointee.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match parenType()
```

**Expected:** 5 matches — `void ()` (line 19), `int (int)` (line 30), `int[4]` (line 47), `void ()` (lines 50 and 51).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(pointsTo(parenType())))
```

**Expected:** 2 matches — `fp` (line 30) and `ptr_to_array` (line 47); `array_of_ptrs` has no parentheses.

### `macroQualifiedType(Matcher<MacroQualifiedType>...)` — Matcher<Type>

Matches a type whose attribute was applied through a macro (`#define CDECL __attribute__((cdecl))`). Writing the attribute directly (`Y`, line 51) yields a plain `AttributedType`; only `X` (line 50) gets the `MacroQualifiedType` wrapper, which remembers the macro name.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match macroQualifiedType()
```

**Expected:** 1 match — `CDECL void ()` inside the typedef of `X` (line 50).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match typedefDecl(hasType(pointsTo(macroQualifiedType())))
```

**Expected:** 1 match — `typedef void (CDECL *X)()` at `types.cpp:50`.

---

## 4.7 — Templates in Types

Templates add a family of type nodes: the *written* specialization `Box<char, 2>`, the parameter `T`, the parameter *after* substitution, the class's own name used inside itself, the CTAD placeholder, and names that cannot be resolved until instantiation.

### `templateSpecializationType(Matcher<TemplateSpecializationType>...)` — Matcher<Type>

Matches a written `Template<Args>` type. The explicit instantiation `template struct Box<int, 3>;` counts only in `AsIs` traversal; the implicit one from `Box<char, 2> box` is a `classTemplateSpecializationDecl`, not a type use.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateSpecializationType()
```

**Expected:** 3 matches — `Box<T, Size>` (line 67), `Box<char, 2>` (line 70), `Holder<Wrap>` (line 84).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(templateSpecializationType()))
```

**Expected:** 3 matches — the parameter `Box<T, Size> b` of `takeSpec` (line 67), `Box<char, 2> box` (line 70) and `Holder<Wrap> holder` (line 84).

### `templateTypeParmType(Matcher<TemplateTypeParmType>...)` — Matcher<Type>

Matches uses of a template *type parameter* (`T`) inside a template. The two `type-parameter-N-0` matches are the anonymous parameter of `Wrap` and the inner parameter of `Holder`'s template template parameter.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateTypeParmType()
```

**Expected:** 13 matches — every `T` spelled inside `Box`, `Dep`, `F`, `Ctad` (11) plus the two unnamed parameters on lines 82–83.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match fieldDecl(hasType(templateTypeParmType()))
```

**Expected:** 1 match — `T value` at `types.cpp:63`.

### `substTemplateTypeParmType(Matcher<SubstTemplateTypeParmType>...)` — Matcher<Type>

Matches the type of something that *was* a `T` and has been replaced by a concrete type in an instantiation. Implicit instantiations (`F(1)`, `Box<char, 2> box`) are skipped by `IgnoreUnlessSpelledInSource`, so reaching `F<int>` needs the default `AsIs` traversal; the *explicit* instantiation `template struct Box<int, 3>;` is spelled in source and shows up in both modes.

```clang-query
match parmVarDecl(hasName("t"), hasType(substTemplateTypeParmType()))
```

**Expected:** 1 match — `int t` of the instantiated `F<int>` (spelled at `types.cpp:76`); the `T t` of the template itself is a `templateTypeParmType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
set output dump
match substTemplateTypeParmType()
```

**Expected:** 3 matches — three `SubstTemplateTypeParmType 'int' sugar ... T` nodes, all from the explicit instantiation `Box<int, 3>` (line 69): the `value` member, the element type of `data[3]` and the `vec` typedef.

### `injectedClassNameType(Matcher<InjectedClassNameType>...)` — Matcher<Type>

Inside a class template, the bare name `Box` means "this specialization" and has its own type node. Writing `Box<T, Size>` instead produces a `TemplateSpecializationType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match parmVarDecl(hasType(injectedClassNameType()))
```

**Expected:** 1 match — `Box b` in `take` (line 66), printed as `Box<T, Size> b`.

### `deducedTemplateSpecializationType(Matcher<DeducedTemplateSpecializationType>...)` — Matcher<Type>

Matches the C++17 CTAD placeholder: `Ctad ct(123)` names the template without arguments and lets the constructor deduce `Ctad<int>`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(deducedTemplateSpecializationType()))
```

**Expected:** 1 match — `Ctad ct(123)` at `types.cpp:80`.

### `dependentNameType(Matcher<DependentNameType>...)` — Matcher<Type>

Matches `typename T::type`: a name that can only be looked up once `T` is known.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match dependentNameType()
```

**Expected:** 1 match — `typename T::type` (line 73).

---

## 4.8 — `auto`, `decltype`, transforms, atomic, complex

### `autoType(Matcher<AutoType>...)` — Matcher<Type>

Matches `auto` (also `auto &`, `auto &&` — the reference wraps the `AutoType`). The written `auto` is *undeduced*; the declaration's type carries the deduced `AutoType`, so `hasDeducedType(...)` (Part 8) only works through `hasType`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match autoType()
```

**Expected:** 4 matches — the `auto` in `ar`, `fr`, `xr` (lines 12–14) and `n` (line 54).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(autoType(hasDeducedType(asString("int")))))
```

**Expected:** 1 match — `auto n = 4` at `types.cpp:54`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match autoType(hasDeducedType(builtinType()))
```

**Expected:** 0 matches — standalone traversal visits the spelled, undeduced `auto`, which has no deduced type yet.

### `decltypeType(Matcher<DecltypeType>...)` — Matcher<Type>

Matches `decltype(expr)`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match decltypeType()
```

**Expected:** 1 match — `decltype(i + f)` (line 55).

### `unaryTransformType(Matcher<UnaryTransformType>...)` — Matcher<Type>

Matches the compiler transform types such as `__underlying_type(E)`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match unaryTransformType()
```

**Expected:** 1 match — `__underlying_type(E)` (line 56).

### `atomicType(Matcher<AtomicType>...)` — Matcher<Type>

Matches C11 `_Atomic(T)`, which Clang also accepts in C++.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match atomicType()
```

**Expected:** 1 match — `_Atomic(int)` (line 57).

### `complexType(Matcher<ComplexType>...)` — Matcher<Type>

Matches C99 `_Complex T`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match complexType()
```

**Expected:** 1 match — `_Complex float` (line 58).

---

## 4.9 — TypeLocs

Each `XxxTypeLoc` matcher is the located twin of `xxxType()`. Counts agree with the written-type counts above, but every match now comes with a caret, and `hasTypeLoc(...)` + `.bind` puts that caret on exactly the type characters.

### `pointerTypeLoc(Matcher<PointerTypeLoc>...)` — Matcher<TypeLoc>

Matches a written `T *`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match pointerTypeLoc()
```

**Expected:** 6 matches — the same six pointer spellings as `pointerType()`, now each with a `types.cpp:LINE:COL` caret.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasTypeLoc(pointerTypeLoc()))
```

**Expected:** 3 matches — `p` (line 9), `fp` (line 30), `ptr_to_array` (line 47).

### `referenceTypeLoc(Matcher<ReferenceTypeLoc>...)` — Matcher<TypeLoc>

Matches a written `T &` or `T &&`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match referenceTypeLoc()
```

**Expected:** 5 matches — lines 10–14.

### `arrayTypeLoc(Matcher<ArrayTypeLoc>...)` — Matcher<TypeLoc>

Matches a written array declarator, whatever its size kind.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match arrayTypeLoc()
```

**Expected:** 8 matches — the eight array spellings listed under `arrayType()`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasName("ca"), hasTypeLoc(arrayTypeLoc().bind("al")))
```

**Expected:** 1 match — `int ca[2]` at `types.cpp:22`; the `al` caret spans `int ca[2]` (an array TypeLoc includes the declarator name and brackets).

### `qualifiedTypeLoc(Matcher<QualifiedTypeLoc>...)` — Matcher<TypeLoc>

Matches a written type with cv-qualifiers, `const int`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match qualifiedTypeLoc()
```

**Expected:** 1 match — `const int` (line 93).

### `templateSpecializationTypeLoc(Matcher<TemplateSpecializationTypeLoc>...)` — Matcher<TypeLoc>

Matches a written `Template<Args>`; `hasAnyTemplateArgumentLoc` / `hasTemplateArgumentLoc(N, ...)` (Part 10) descend into the arguments.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateSpecializationTypeLoc()
```

**Expected:** 3 matches — `Box<T, Size>` (line 67), `Box<char, 2>` (line 70), `Holder<Wrap>` (line 84).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasName("box"),
  hasTypeLoc(templateSpecializationTypeLoc().bind("tsl")))
```

**Expected:** 1 match — `Box<char, 2> box` at `types.cpp:70`; the `tsl` caret covers `Box<char, 2>` only.

### `functionTypeLoc(Matcher<FunctionTypeLoc>...)` — Matcher<TypeLoc>

Matches a written function type such as `void (int)` or the `char ()` inside `char (*fn_ptr)()`.

**Not in clang-query 22** — trunk-only; the matcher exists in the reference but is not registered in this build. Convert a type matcher with `loc(...)` instead:

```clang-query
set traversal IgnoreUnlessSpelledInSource
match functionDecl(hasName("h"), hasTypeLoc(loc(functionProtoType())))
```

**Expected:** 1 match — `void h(int) {}` at `types.cpp:32`.

---

## 4.10 — Nested Name Specifiers, Template Arguments, Template Names

Three small node kinds that are neither declarations nor types but appear *inside* them: the `ns::` prefix of a qualified name, the arguments in `<...>`, and the template being named.

### `nestedNameSpecifier(Matcher<NestedNameSpecifier>...)` — Matcher<NestedNameSpecifier>

Matches a qualifier such as `nn::`, `A::` or `T::`. `specifiesNamespace(...)` / `specifiesType(...)` (Part 6) narrow by what is before the `::`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match nestedNameSpecifier()
```

**Expected:** 9 matches — `A::` ×4 (lines 18–19), `lib::` (line 45), `T::` (line 73), `Q::` ×2 (lines 89–90), `nn::` (line 92).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match varDecl(hasType(hasQualifier(
  nestedNameSpecifier(specifiesNamespace(hasName("nn"))))))
```

**Expected:** 1 match — `nn::Q q` at `types.cpp:92`.

### `nestedNameSpecifierLoc(Matcher<NestedNameSpecifierLoc>...)` — Matcher<NestedNameSpecifierLoc>

The located twin: same qualifiers, each with a caret on the `xx::` characters. `loc(nestedNameSpecifier(...))` converts a specifier matcher.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match nestedNameSpecifierLoc()
```

**Expected:** 9 matches — the same nine qualifiers, now with `types.cpp:LINE:COL` carets.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match nestedNameSpecifierLoc(loc(specifiesType(
  hasDeclaration(recordDecl(hasName("A"))))))
```

**Expected:** 4 matches — the four `A::` on lines 18–19.

### `templateArgument(Matcher<TemplateArgument>...)` — Matcher<TemplateArgument>

Matches one argument of a template specialization: a type (`char`), a value (`2`) or a template (`Wrap`). It is **not a valid top-level matcher** in clang-query (there is no standalone traversal of template arguments), so reach it through `hasAnyTemplateArgument` / `hasTemplateArgument(N, ...)` on a specialization type or declaration (Part 10).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateSpecializationType(hasAnyTemplateArgument(templateArgument()))
```

**Expected:** 3 matches — `Box<T, Size>`, `Box<char, 2>`, `Holder<Wrap>`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateSpecializationType(hasTemplateArgument(0,
  templateArgument(refersToType(asString("char")))))
```

**Expected:** 1 match — `Box<char, 2>` (line 70).

### `templateArgumentLoc(Matcher<TemplateArgumentLoc>...)` — Matcher<TemplateArgumentLoc>

The located argument. Unlike `templateArgument()`, this one *is* traversed standalone, so you can count every written argument.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateArgumentLoc()
```

**Expected:** 7 matches — `T`, `Size` (line 67), `int`, `3` (line 69), `char`, `2` (line 70), `Wrap` (line 84).

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateArgumentLoc(hasTypeLoc(loc(asString("char"))))
```

**Expected:** 1 match — the `char` in `Box<char, 2>` at `types.cpp:70:5`.

### `templateName(Matcher<TemplateName>...)` — Matcher<TemplateName>

Matches the *name of a template* as a value: the `Wrap` passed to `Holder<Wrap>`. Like `templateArgument()`, it cannot stand alone; the only way in is `templateArgument(refersToTemplate(templateName()))`.

```clang-query
set traversal IgnoreUnlessSpelledInSource
match templateSpecializationType(hasAnyTemplateArgument(
  templateArgument(refersToTemplate(templateName()))))
```

**Expected:** 1 match — `Holder<Wrap>` (line 84).

```clang-query
match classTemplateSpecializationDecl(hasTemplateArgument(0,
  templateArgument(refersToTemplate(templateName()))))
```

**Expected:** 1 match — the implicit specialization `Holder<Wrap>` (visible only in `AsIs` traversal), located at its template on `types.cpp:83`.

---

## 4.11 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| `Type` vs `QualType` vs `TypeLoc` | `type()` binds print no caret, `typeLoc()` binds do; `isConstQualified()` lives on `qualType()` only |
| Standalone vs nested | `match pointerType()` counts spellings; `varDecl(hasType(pointerType()))` finds declarations — and `AsIs` adds ~100 implicit builtins |
| Sugar | `Int ti` is a `typedefType`, `T ut` a `usingType`, `auto n` an `autoType`; none is a `builtinType` until desugared |
| Written vs declared | `int ia[] = {2, 3}` is an `incompleteArrayType` where written but a `constantArrayType` as declared; `int param[]` is a `decayedType` |
| Templates | `T` is `templateTypeParmType`, its instantiation is `substTemplateTypeParmType`, bare `Box` inside `Box` is `injectedClassNameType` |
| Non-top-level nodes | `templateArgument()` and `templateName()` only work inside `hasAnyTemplateArgument` / `refersToTemplate` |

**Quiz.** Find every variable whose declared type is an array whose *element* type is a pointer. (You need `varDecl`, `hasType`, `arrayType` and one Part 8 traversal matcher that descends into an array's element.)

> [!hint]- Hint
> `arrayType(...)` accepts `hasElementType(Matcher<Type>)`. Element types are `Type`s, so `pointerType()` fits directly.

> [!success]- Answer
> `varDecl(hasType(arrayType(hasElementType(pointerType()))))` — 1 match: `int *array_of_ptrs[4]` at `types.cpp:48`. `ptr_to_array` is the other way round (a pointer whose pointee is an array).

---

[← Part 3 — Node Matchers II — Statements & Expressions](part_3_node_matchers_stmts.md) | [Part 5 — Narrowing Matchers I — Logic & Declarations →](part_5_narrowing_logic_decls.md)
