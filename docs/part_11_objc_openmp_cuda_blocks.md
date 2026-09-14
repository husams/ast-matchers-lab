# Part 11 — Objective-C, OpenMP, CUDA & Blocks

[← Part 10 — Traversal Matchers III — Types, TypeLocs & Templates](part_10_traversal_types_templates.md) | [Part 12 — Capstone — Real Checks in Pure clang-query →](part_12_capstone.md)

**Sample:** `manifests/objc.m` · flags: `-fobjc-exceptions`

This part uses four samples. The default is `manifests/objc.m`; the OpenMP,
CUDA and Blocks sections re-declare their own sample, and a few blocks switch
files with a `# sample:` first line that you can paste as-is.

| Sample | Flags after `--` | Why those flags |
|--------|------------------|-----------------|
| `manifests/objc.m` | `-fobjc-exceptions` | `.m` already selects Objective-C; the flag documents that `@try` is in play (the parse works without it). No ARC, so `release` messages are legal. |
| `manifests/openmp.cpp` | `-std=c++23 -fopenmp` | Without `-fopenmp` the pragmas are ignored and no `omp*` node exists. Clang 22 defaults to OpenMP 5.1, so `default(private)` parses without `-fopenmp-version=51`. |
| `manifests/cuda.cu` | `-x cuda --cuda-host-only -nocudainc -nocudalib` | Host-side parse only, no CUDA SDK. The sample declares `cudaConfigureCall` by hand because `<<<…>>>` lowers to a call of it. |
| `manifests/blocks.cpp` | `-std=c++23 -fblocks` | `^` blocks are an extension that must be switched on. |

## What You'll Learn

- Why the reference lists Objective-C, OpenMP, CUDA and Blocks matchers at all, and when you would reach for them.
- The Objective-C declaration family: interfaces, implementations, categories, protocols, ivars, properties and methods, plus the class-hierarchy narrowers that also work on `@interface`.
- Message sends: selectors (unary, keyword, null), class vs instance messages, receivers, arguments and callees.
- OpenMP directives and clauses, including the `default(...)` kinds and the "is this clause allowed here" check.
- The single CUDA matcher and how to get a `<<<…>>>` launch to parse with no SDK.
- Blocks: the declaration, the expression, the pointer type and its `ParenType`-wrapped pointee.
- Which five OpenMP names the reference lists but this clang-query build does not register, and what to use instead.

## The Big Picture

Clang is one front end for several languages. Objective-C, OpenMP pragmas,
CUDA kernels and the Blocks extension all produce their own node classes in
the same AST, and the matcher DSL has a matcher for each of them. The rows in
this part are the reference's tail: rarely used in C++ code bases, but they
are the *only* way to write a check for an `@implementation`, a `#pragma omp
parallel`, a kernel launch or a `^{}` literal.

```
   language        node family            entry matchers
   ─────────────   ─────────────────────  ────────────────────────────────
   Objective-C     ObjC*Decl              objcInterfaceDecl, objcMethodDecl…
                   ObjCMessageExpr        objcMessageExpr + selector narrowers
                   ObjCAt*Stmt            objcTryStmt, objcCatchStmt…
   OpenMP          OMPExecutableDirective ompExecutableDirective
                   OMPClause              ompDefaultClause (nested only)
   CUDA            CUDAKernelCallExpr     cudaKernelCallExpr
   Blocks          BlockDecl / BlockExpr  blockDecl, blockExpr
                   BlockPointerType       blockPointerType
```

Two conventions carry over unchanged from earlier parts. Node matchers such
as `objcMessageExpr()` are the entry points; narrowing matchers such as
`hasSelector(...)` and traversal matchers such as `hasReceiver(...)` go
inside them. And the generic matchers you already know still apply: an
`ObjCMethodDecl` is a `NamedDecl`, so `hasName`, `isImplicit`, `hasParameter`
and friends all work on it.

One OpenMP wrinkle is worth knowing before you type anything. `OMPClause` is
not a top-level node kind in clang-query, so `ompDefaultClause()` on its own
is refused with "Not a valid top-level matcher"; it only ever appears inside
`ompExecutableDirective(hasAnyClause(...))`.

Start a session for this part:

```bash
$LLVM/bin/clang-query manifests/objc.m -- -fobjc-exceptions
```

The sample declares its own tiny runtime: a root class `NSObject` marked
`__attribute__((objc_root_class))`, an empty `NSString` (an `@"..."` literal
has type `NSString *`, so the class must exist), two protocols, a class
`Foo` with ivars, properties, class and instance methods, a category
`Foo (Additions)`, subclasses `Bar` and `Baz`, and one function `useIt` that
sends messages, opens an `@autoreleasepool` and runs `@try/@catch/@finally`.

---

## 11.1 — Why these rows exist

The reference is generated from the matcher headers, and those headers cover
every language Clang parses. When you write a check for a mixed code base
(an iOS app with C++ under the hood, a scientific kernel with OpenMP
pragmas, a CUDA project) you meet these node kinds and need a matcher that
names them. Nothing here changes how the DSL works: the same
`node(narrowing, traversal(...))` shape applies, and the same `set output
dump` trick shows you the node names to target.

Practical consequences:

- **Flags decide whether the nodes exist.** Forget `-fopenmp` and every `omp*`
  matcher returns 0 matches without complaint. Forget `-fblocks` and
  `blocks.cpp` does not even parse.
- **Language-specific nodes are ordinary nodes.** `objcMethodDecl()` is a
  `Decl`, `objcMessageExpr()` is an `Expr`, `ompExecutableDirective()` is a
  `Stmt`. Everything from Parts 5–10 composes with them.
- **Five names are missing from this build.** `ompCountsClause`,
  `ompFromClause`, `ompToClause`, `ompSplitDirective` and
  `ompTargetUpdateDirective` were added to the reference after the
  clang-query 22 registry was frozen. Their entries below say so and show
  the nearest working query.

---

## 11.2 — Objective-C declarations

Every Objective-C declaration form has a node matcher. The names follow the
keyword: `@interface` is `objcInterfaceDecl`, `@implementation` is
`objcImplementationDecl`, a category `@interface Foo (Additions)` is
`objcCategoryDecl`, its `@implementation` is `objcCategoryImplDecl`,
`@protocol` is `objcProtocolDecl`. Inside those: `objcIvarDecl`,
`objcPropertyDecl` and `objcMethodDecl`.

### `objcInterfaceDecl(Matcher<ObjCInterfaceDecl>...)` — Matcher<Decl>

Matches an `@interface` declaration. Categories are a separate node kind and
do not show up here. The sixth match has no location: it is the implicit
`@class Protocol;` that Clang declares for every Objective-C translation
unit.

```clang-query
match objcInterfaceDecl()
```

**Expected:** 6 matches — `NSObject` at `objc.m:10`, `NSString` at `objc.m:26`, `Foo` at `objc.m:37`, `Bar` at `objc.m:81`, `Baz` at `objc.m:89`, plus the implicit `Protocol`.

Drop the implicit one with a narrower you already know:

```clang-query
match objcInterfaceDecl(unless(isImplicit()))
```

**Expected:** 5 matches — the five `@interface` lines above.

### `objcImplementationDecl(Matcher<ObjCImplementationDecl>...)` — Matcher<Decl>

Matches an `@implementation` of a class (not of a category).

```clang-query
match objcImplementationDecl()
```

**Expected:** 4 matches — `NSObject` at `objc.m:18`, `Foo` at `objc.m:50`, `Bar` at `objc.m:85`, `Baz` at `objc.m:92`.

### `objcCategoryDecl(Matcher<ObjCCategoryDecl>...)` — Matcher<Decl>

Matches a category interface, `@interface Foo (Additions)`.

```clang-query
match objcCategoryDecl()
```

**Expected:** 1 match — `Foo (Additions)` at `objc.m:73`.

### `objcCategoryImplDecl(Matcher<ObjCCategoryImplDecl>...)` — Matcher<Decl>

Matches a category implementation, `@implementation Foo (Additions)`.

```clang-query
match objcCategoryImplDecl()
```

**Expected:** 1 match — `Foo (Additions)` at `objc.m:77`.

### `objcProtocolDecl(Matcher<ObjCProtocolDecl>...)` — Matcher<Decl>

Matches an `@protocol` declaration.

```clang-query
match objcProtocolDecl()
```

**Expected:** 2 matches — `FooDelegate` at `objc.m:29`, `Loggable` at `objc.m:33`.

### `objcIvarDecl(Matcher<ObjCIvarDecl>...)` — Matcher<Decl>

Matches an instance variable declared in the `{ ... }` block of an
interface or implementation. Properties are not ivars; `@synthesize` here
reuses the existing ivars, so nothing is added.

```clang-query
match objcIvarDecl()
```

**Expected:** 3 matches — `isa` at `objc.m:11`, `_enabled` at `objc.m:38`, `_name` at `objc.m:39`.

### `objcPropertyDecl(Matcher<ObjCPropertyDecl>...)` — Matcher<Decl>

Matches an `@property` declaration.

```clang-query
match objcPropertyDecl()
```

**Expected:** 2 matches — `enabled` at `objc.m:41`, `name` at `objc.m:42`.

### `objcMethodDecl(Matcher<ObjCMethodDecl>...)` — Matcher<Decl>

Matches a method declaration, both the prototype in the `@interface` and the
definition in the `@implementation`. Method names are selectors, so
`hasName` takes the full selector: `"method"` for a unary one,
`"setName:enabled:"` for a keyword one.

```clang-query
match objcMethodDecl(hasName("method"))
```

**Expected:** 2 matches — the prototype at `objc.m:44` and the definition at `objc.m:59`.

### `isClassMethod()` — Matcher<ObjCMethodDecl>

Narrows to `+` methods.

```clang-query
match objcMethodDecl(isClassMethod())
```

**Expected:** 4 matches — `+alloc` at `objc.m:13` and `objc.m:19`, `+fooWithName:` at `objc.m:43` and `objc.m:54`.

### `isInstanceMethod()` — Matcher<ObjCMethodDecl>

Narrows to `-` methods. Combined with `hasName` it also finds the protocol's
requirement, since a protocol method is an `ObjCMethodDecl` too.

```clang-query
match objcMethodDecl(isInstanceMethod(), hasName("log"))
```

**Expected:** 3 matches — `Loggable`'s requirement at `objc.m:34`, `Foo`'s prototype at `objc.m:47`, its definition at `objc.m:70`.

### `isDefinition()` — Matcher<ObjCMethodDecl>

Matches a method that has a body, i.e. the one in the `@implementation`.
The prototype in the `@interface` is only a declaration.

```clang-query
match objcMethodDecl(isDefinition(), hasName("method"))
```

**Expected:** 1 match — the definition at `objc.m:59`.

### `hasParameter(unsigned N, Matcher<ParmVarDecl> InnerMatcher)` — Matcher<BlockDecl>, Matcher<ObjCMethodDecl>

The N-th parameter (0-based) of a method or a block. Parameters are plain
`ParmVarDecl`s, so `hasName`, `hasType` and the rest apply. For a method both
the prototype and the definition match.

```clang-query
match objcMethodDecl(hasParameter(1, hasName("flag")))
```

**Expected:** 2 matches — `setName:enabled:` at `objc.m:45` and `objc.m:63`.

The same matcher on a block:

```clang-query
# sample: manifests/blocks.cpp -std=c++23 -fblocks
match blockDecl(hasParameter(0, hasName("p")))
```

**Expected:** 1 match — the `^(int p)` block at `blocks.cpp:10`.

### `hasAnyParameter(Matcher<ParmVarDecl> InnerMatcher)` — Matcher<BlockDecl>, Matcher<ObjCMethodDecl>

Any parameter of a method or a block matches the inner matcher.

```clang-query
match objcMethodDecl(hasAnyParameter(hasName("foo")))
```

**Expected:** 3 matches — `fooDidFinish:` in the protocol at `objc.m:30`, in `Bar`'s interface at `objc.m:82`, in its implementation at `objc.m:86`.

```clang-query
# sample: manifests/blocks.cpp -std=c++23 -fblocks
match blockDecl(hasAnyParameter(hasName("msg")))
```

**Expected:** 1 match — the `report` block at `blocks.cpp:11`.

### `hasTypeLoc(Matcher<TypeLoc> Inner)` — Matcher<BlockDecl>, Matcher<ObjCPropertyDecl>

The written type of a property, or the written signature of a block. A
block with no written signature (`^{}`) has no type location and never
matches.

```clang-query
match objcPropertyDecl(hasTypeLoc(loc(asString("NSString *"))))
```

**Expected:** 1 match — `@property (readonly) NSString *name` at `objc.m:42`.

```clang-query
# sample: manifests/blocks.cpp -std=c++23 -fblocks
match blockDecl(hasTypeLoc(loc(functionProtoType(parameterCountIs(2)))))
```

**Expected:** 1 match — the two-parameter `report` block at `blocks.cpp:11`.

```clang-query
# sample: manifests/blocks.cpp -std=c++23 -fblocks
match blockDecl(hasTypeLoc(loc(functionProtoType())))
```

**Expected:** 3 matches — the blocks at `blocks.cpp:10`, `blocks.cpp:11` and `blocks.cpp:13`; the `^{}` at line 15 wrote no signature.

### `isDerivedFrom(std::string BaseName)` — Matcher<ObjCInterfaceDecl>

The class-hierarchy narrower from Part 5 also works on `@interface`: it
matches a class that directly or indirectly subclasses the named base. The
string form is a shortcut for `isDerivedFrom(hasName(...))`; both forms are
accepted. A class is not derived from itself.

```clang-query
match objcInterfaceDecl(isDerivedFrom("NSObject"))
```

**Expected:** 4 matches — `NSString` at `objc.m:26`, `Foo` at `objc.m:37`, `Bar` at `objc.m:81`, `Baz` at `objc.m:89`.

```clang-query
match objcInterfaceDecl(isDerivedFrom(hasName("Foo")))
```

**Expected:** 2 matches — `Bar` at `objc.m:81`, `Baz` at `objc.m:89`.

### `isDirectlyDerivedFrom(std::string BaseName)` — Matcher<ObjCInterfaceDecl>

Only the immediate subclass.

```clang-query
match objcInterfaceDecl(isDirectlyDerivedFrom("Foo"))
```

**Expected:** 1 match — `Bar` at `objc.m:81`.

### `isSameOrDerivedFrom(std::string BaseName)` — Matcher<ObjCInterfaceDecl>

Like `isDerivedFrom` but the base itself also matches.

```clang-query
match objcInterfaceDecl(isSameOrDerivedFrom("Bar"))
```

**Expected:** 2 matches — `Bar` at `objc.m:81`, `Baz` at `objc.m:89`.

### `hasType(Matcher<Decl> InnerMatcher)` — Matcher<ObjCInterfaceDecl>

The `hasType` overload that takes a *declaration* matcher resolves the
node's type to its declaration. clang-query registers it for `Expr`,
`ValueDecl`, `FriendDecl`, `CXXBaseSpecifier` and `ObjCInterfaceDecl`. The
useful form is on an expression or value whose type *is* the interface: an
object pointer's type is `Foo *` (an `ObjCObjectPointerType`), so to find
plain `Foo` you need a dereference. The sample has one, `(void)*foo;`.

```clang-query
match unaryOperator(hasType(objcInterfaceDecl(hasName("Foo"))))
```

**Expected:** 1 match — `*foo` at `objc.m:101`.

For pointers go through the type: `pointsTo` (Part 10) on the
`QualType` overload of `hasType`, then the interface declaration.

```clang-query
match objcIvarDecl(hasType(pointsTo(objcInterfaceDecl(hasName("NSString")))))
```

**Expected:** 1 match — `NSString *_name` at `objc.m:39`.

Applied to the interface node itself, this overload asks for the *pointee*
of the interface's own type. That type is not a pointer, so in LLVM 22 the
matcher never fires on an `@interface`:

```clang-query
match objcInterfaceDecl(hasType(objcInterfaceDecl()))
```

**Expected:** 0 matches — the direct form is registered but has nothing to match.

### `objcObjectPointerType(Matcher<ObjCObjectPointerType>...)` — Matcher<Type>

An Objective-C object pointer, `Foo *` or `id`, which is a different node
from a C `pointerType()` even though it is spelled the same. Types have no
location, so the bare query prints only a count.

```clang-query
match objcObjectPointerType()
```

**Expected:** 12 matches — one per distinct object-pointer type in the file.

Wrap it in a declaration matcher to see where those types are used:

```clang-query
match parmVarDecl(hasType(objcObjectPointerType()))
```

**Expected:** 6 matches — the `name` parameters at `objc.m:43`, `objc.m:45`, `objc.m:54`, `objc.m:63` and `foo`, `bar` at `objc.m:95`.

---

## 11.3 — Objective-C statements & messages

A message send `[receiver selector:arg]` is an `ObjCMessageExpr`. Its
*selector* is the method name with colons (`setName:enabled:`), it is a
*class message* when the receiver is a class name and an *instance message*
otherwise, and its arguments are ordinary expressions. Around messages the
language adds a few statements of its own: `@try`, `@catch`, `@finally`,
`@throw` and `@autoreleasepool`.

```
   [bar setName:@"bar" enabled:0]
    │    │      │          │
    │    │      └──────────┴── arguments  → hasArgument / hasAnyArgument
    │    └── selector "setName:enabled:"  → hasSelector / numSelectorArgs
    └── receiver expression              → hasReceiver / hasReceiverType
```

### `objcMessageExpr(Matcher<ObjCMessageExpr>...)` — Matcher<Stmt>

Matches every message send. Nested sends count separately:
`[[Foo alloc] init]` is two messages, and the inner one is reported at the
column of `Foo`.

```clang-query
match objcMessageExpr()
```

**Expected:** 14 matches — every `[...]` in `objc.m`, from `[[Foo alloc] init]` at `objc.m:55` to `[foo release]` at `objc.m:113`.

### `objcStringLiteral(Matcher<ObjCStringLiteral>...)` — Matcher<Stmt>

Matches an `@"..."` literal.

```clang-query
match objcStringLiteral()
```

**Expected:** 3 matches — `@"default"` at `objc.m:61`, `@"bar"` at `objc.m:98`, `@"fresh"` at `objc.m:102`.

### `objcIvarRefExpr(Matcher<ObjCIvarRefExpr>...)` — Matcher<Stmt>

Matches a use of an instance variable inside a method, written bare
(`_name`) or through `self->_name`. It is not a `declRefExpr`; ivars have
their own reference node.

```clang-query
match objcIvarRefExpr()
```

**Expected:** 4 matches — `_enabled` and `_name` at `objc.m:60`–`objc.m:61`, and again at `objc.m:64`–`objc.m:65`.

`hasDeclaration` selects one ivar:

```clang-query
match objcIvarRefExpr(hasDeclaration(objcIvarDecl(hasName("_name"))))
```

**Expected:** 2 matches — `objc.m:61` and `objc.m:64`.

### `autoreleasePoolStmt(Matcher<ObjCAutoreleasePoolStmt>...)` — Matcher<Stmt>

Matches an `@autoreleasepool { ... }` statement. Its only child is the
compound statement, so use `hasDescendant` to look inside.

```clang-query
match autoreleasePoolStmt(hasDescendant(declStmt()))
```

**Expected:** 1 match — the pool at `objc.m:103`, which declares `int x`.

### `objcTryStmt(Matcher<ObjCAtTryStmt>...)` — Matcher<Stmt>

Matches an `@try` statement (the whole try/catch/finally construct).

```clang-query
match objcTryStmt()
```

**Expected:** 1 match — `@try` at `objc.m:108`.

### `objcCatchStmt(Matcher<ObjCAtCatchStmt>...)` — Matcher<Stmt>

Matches an `@catch (...)` clause.

```clang-query
match objcCatchStmt()
```

**Expected:** 1 match — `@catch (Foo *e)` at `objc.m:110`.

### `objcFinallyStmt(Matcher<ObjCAtFinallyStmt>...)` — Matcher<Stmt>

Matches an `@finally` clause.

```clang-query
match objcFinallyStmt()
```

**Expected:** 1 match — `@finally` at `objc.m:112`.

### `objcThrowStmt(Matcher<ObjCAtThrowStmt>...)` — Matcher<Stmt>

Matches an `@throw` statement.

```clang-query
match objcThrowStmt()
```

**Expected:** 1 match — `@throw e` at `objc.m:111`.

### `hasSelector(std::string BaseName)` — Matcher<ObjCMessageExpr>

The selector, spelled exactly as `Selector::getAsString()` prints it:
colons included, no spaces.

```clang-query
match objcMessageExpr(hasSelector("setName:enabled:"))
```

**Expected:** 2 matches — `objc.m:56` and `objc.m:98`.

### `hasAnySelector(StringRef, ..., StringRef)` — Matcher<ObjCMessageExpr>

Any of several exact selectors.

```clang-query
match objcMessageExpr(hasAnySelector("method", "extra"))
```

**Expected:** 3 matches — `[self method]` at `objc.m:78`, `[foo method]` at `objc.m:97`, `[foo extra]` at `objc.m:109`.

### `matchesSelector(StringRef RegExp, Regex::RegexFlags Flags = NoFlags)` — Matcher<ObjCMessageExpr>

Regular-expression search over the selector string. Flags are passed as a
quoted string, combinable with `|`.

```clang-query
match objcMessageExpr(matchesSelector("^set"))
```

**Expected:** 2 matches — the two `setName:enabled:` sends at `objc.m:56` and `objc.m:98`.

```clang-query
match objcMessageExpr(matchesSelector("name", "IgnoreCase"))
```

**Expected:** 3 matches — `setName:enabled:` twice and `fooWithName:` at `objc.m:102`.

### `hasUnarySelector()` — Matcher<ObjCMessageExpr>

A selector with no colon: `alloc`, `init`, `release`, `method`, `log`,
`extra`.

```clang-query
match objcMessageExpr(hasUnarySelector())
```

**Expected:** 10 matches — every colon-free send, e.g. `[Foo alloc]` and `[... init]` at `objc.m:55`, `[baz log]` at `objc.m:106`.

### `hasKeywordSelector()` — Matcher<ObjCMessageExpr>

A selector with at least one colon.

```clang-query
match objcMessageExpr(hasKeywordSelector())
```

**Expected:** 4 matches — `objc.m:56`, `objc.m:98`, `objc.m:99` (`countFrom:to:`), `objc.m:102` (`fooWithName:`).

### `hasNullSelector()` — Matcher<ObjCMessageExpr>

The empty selector. Clang never produces one from well-formed source; the
reference notes it "may represent an error condition in the tree". So the
useful spelling is its negation, which proves every send has a selector:

```clang-query
match objcMessageExpr(unless(hasNullSelector()))
```

**Expected:** 14 matches — all message sends.

```clang-query
match objcMessageExpr(hasNullSelector())
```

**Expected:** 0 matches — no malformed sends in the sample.

### `numSelectorArgs(unsigned N)` — Matcher<ObjCMessageExpr>

The number of colons in the selector, which equals the number of
arguments.

```clang-query
match objcMessageExpr(numSelectorArgs(2))
```

**Expected:** 3 matches — `setName:enabled:` at `objc.m:56` and `objc.m:98`, `countFrom:to:` at `objc.m:99`.

### `isClassMessage()` — Matcher<ObjCMessageExpr>

The receiver is a class name, `[Foo alloc]`.

```clang-query
match objcMessageExpr(isClassMessage())
```

**Expected:** 3 matches — `[Foo alloc]` at `objc.m:55`, `[Baz alloc]` at `objc.m:96`, `[Foo fooWithName:...]` at `objc.m:102`.

### `isInstanceMessage()` — Matcher<ObjCMessageExpr>

The receiver is an object expression, including `self` and the result of
another send.

```clang-query
match objcMessageExpr(isInstanceMessage())
```

**Expected:** 11 matches — the remaining sends, e.g. `[... init]` at `objc.m:55`, `[self method]` at `objc.m:78`.

### `argumentCountIs(unsigned N)` — Matcher<ObjCMessageExpr>

Exactly N arguments, the same matcher you used on `callExpr` in Part 6.

```clang-query
match objcMessageExpr(argumentCountIs(2))
```

**Expected:** 3 matches — `objc.m:56`, `objc.m:98`, `objc.m:99`.

### `argumentCountAtLeast(unsigned N)` — Matcher<ObjCMessageExpr>

At least N arguments.

```clang-query
match objcMessageExpr(argumentCountAtLeast(1))
```

**Expected:** 4 matches — the three two-argument sends plus `fooWithName:` at `objc.m:102`.

### `hasArgument(unsigned N, Matcher<Expr> InnerMatcher)` — Matcher<ObjCMessageExpr>

The N-th argument (0-based), whatever the selector's keyword for it is.

```clang-query
match objcMessageExpr(hasArgument(1, integerLiteral()))
```

**Expected:** 3 matches — `enabled:1` at `objc.m:56`, `enabled:0` at `objc.m:98`, `to:10` at `objc.m:99`.

### `hasAnyArgument(Matcher<Expr> InnerMatcher)` — Matcher<ObjCMessageExpr>

Any argument matches.

```clang-query
match objcMessageExpr(hasAnyArgument(objcStringLiteral()))
```

**Expected:** 2 matches — `setName:@"bar"` at `objc.m:98`, `fooWithName:@"fresh"` at `objc.m:102`.

### `hasReceiver(Matcher<Expr> InnerMatcher)` — Matcher<ObjCMessageExpr>

The receiver *expression* of an instance message. Class messages have no
receiver expression and never match. Note that a `ParmVarDecl` is a
`VarDecl`, so `varDecl(hasName("foo"))` also catches the `foo` parameter of
`fooDidFinish:` in `Bar`.

```clang-query
match objcMessageExpr(hasReceiver(declRefExpr(to(varDecl(hasName("foo"))))))
```

**Expected:** 5 matches — `[foo release]` at `objc.m:86`, `[foo method]` at `objc.m:97`, `[foo countFrom:...]` at `objc.m:99`, `[foo extra]` at `objc.m:109`, `[foo release]` at `objc.m:113`.

### `hasReceiverType(Matcher<QualType> InnerMatcher)` — Matcher<ObjCMessageExpr>

The receiver's *type*. For an instance message that is the object pointer
type (`Bar *`); for a class message it is the interface type itself
(`Foo`), so this is the one receiver matcher that also reaches class
messages.

```clang-query
match objcMessageExpr(hasReceiverType(asString("Bar *")))
```

**Expected:** 1 match — `[bar setName:@"bar" enabled:0]` at `objc.m:98`.

```clang-query
match objcMessageExpr(hasReceiverType(asString("Foo")))
```

**Expected:** 2 matches — the class messages `[Foo alloc]` at `objc.m:55` and `[Foo fooWithName:...]` at `objc.m:102`.

### `callee(Matcher<Decl> InnerMatcher)` — Matcher<ObjCMessageExpr>

The method declaration the message resolves to. This is how you select by
the *declared* method rather than by selector text, e.g. only class methods.

```clang-query
match objcMessageExpr(callee(objcMethodDecl(hasName("alloc"))))
```

**Expected:** 2 matches — `[Foo alloc]` at `objc.m:55`, `[Baz alloc]` at `objc.m:96`.

---

## 11.4 — OpenMP

**Sample:** `manifests/openmp.cpp` · flags: `-std=c++23 -fopenmp`

```bash
$LLVM/bin/clang-query manifests/openmp.cpp -- -std=c++23 -fopenmp
```

With `-fopenmp` each `#pragma omp ...` becomes an `OMPExecutableDirective`
statement wrapping the statement that follows it (the *structured block*).
Standalone directives such as `taskyield` and `barrier` have no structured
block. Clauses (`default(none)`, `schedule(...)`) hang off the directive as
`OMPClause` children, and `OMPClause` is *not* a top-level node kind in
clang-query, so a clause matcher only works inside `hasAnyClause(...)`.
Likewise `anything()` is not accepted as an `OMPClause` matcher; give
`hasAnyClause` a real clause matcher.

The sample has twelve directives: `parallel` with `;`, `parallel` with
`{}`, four `parallel default(...)`, `parallel for`, `for`, `taskyield`,
`barrier`, and two `target update`.

### `ompExecutableDirective(Matcher<OMPExecutableDirective>...)` — Matcher<Stmt>

Matches any `#pragma omp` executable directive.

```clang-query
match ompExecutableDirective()
```

**Expected:** 12 matches — every pragma from `openmp.cpp:7` to `openmp.cpp:39`.

### `isStandaloneDirective()` — Matcher<OMPExecutableDirective>

A directive that cannot have a structured block.

```clang-query
match ompExecutableDirective(isStandaloneDirective())
```

**Expected:** 4 matches — `taskyield` at `openmp.cpp:33`, `barrier` at `openmp.cpp:35`, `target update` at `openmp.cpp:37` and `openmp.cpp:39`.

### `hasStructuredBlock(Matcher<Stmt> InnerMatcher)` — Matcher<OMPExecutableDirective>

The statement the directive applies to. Standalone directives never match.
The first `parallel` in the sample is followed by a bare `;`, a null
statement.

```clang-query
match ompExecutableDirective(hasStructuredBlock(nullStmt()))
```

**Expected:** 1 match — `#pragma omp parallel` at `openmp.cpp:7`.

```clang-query
match ompExecutableDirective(hasStructuredBlock(compoundStmt()))
```

**Expected:** 5 matches — the five `parallel` directives with `{}` bodies at `openmp.cpp:10`–`openmp.cpp:22`.

### `hasAnyClause(Matcher<OMPClause> InnerMatcher)` — Matcher<OMPExecutableDirective>

Any clause of the directive matches. This is the only door to clause
matchers.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause()))
```

**Expected:** 4 matches — the `default(...)` directives at `openmp.cpp:13`, `openmp.cpp:16`, `openmp.cpp:19`, `openmp.cpp:22`.

### `isAllowedToContainClauseKind(OpenMPClauseKind CKind)` — Matcher<OMPExecutableDirective>

Whether the directive *kind* may carry a given clause kind, regardless of
whether it actually does. The argument is the `OpenMPClauseKind` enumerator
as a quoted string, `"OMPC_default"`, `"OMPC_schedule"`, `"OMPC_to"` and so
on.

```clang-query
match ompExecutableDirective(isAllowedToContainClauseKind("OMPC_default"))
```

**Expected:** 7 matches — every `parallel` and `parallel for` (`openmp.cpp:7`–`openmp.cpp:25`); a plain `for` may not carry `default`.

```clang-query
match ompExecutableDirective(isAllowedToContainClauseKind("OMPC_schedule"))
```

**Expected:** 2 matches — `parallel for` at `openmp.cpp:25` and `for` at `openmp.cpp:29`.

### `ompDefaultClause(Matcher<OMPDefaultClause>...)` — Matcher<OMPClause>

Matches a `default(...)` clause. On its own clang-query answers "Not a valid
top-level matcher"; nest it.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause()))
```

**Expected:** 4 matches — `default(none)`, `default(shared)`, `default(private)`, `default(firstprivate)` at `openmp.cpp:13`–`openmp.cpp:22`.

### `isNoneKind()` — Matcher<OMPDefaultClause>

The clause is `default(none)`.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause(isNoneKind())))
```

**Expected:** 1 match — `openmp.cpp:13`.

### `isSharedKind()` — Matcher<OMPDefaultClause>

The clause is `default(shared)`.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause(isSharedKind())))
```

**Expected:** 1 match — `openmp.cpp:16`.

### `isPrivateKind()` — Matcher<OMPDefaultClause>

The clause is `default(private)`, an OpenMP 5.1 addition that Clang 22
accepts by default.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause(isPrivateKind())))
```

**Expected:** 1 match — `openmp.cpp:19`.

### `isFirstPrivateKind()` — Matcher<OMPDefaultClause>

The clause is `default(firstprivate)`.

```clang-query
match ompExecutableDirective(hasAnyClause(ompDefaultClause(isFirstPrivateKind())))
```

**Expected:** 1 match — `openmp.cpp:22`.

### `ompTargetUpdateDirective(Matcher<OMPTargetUpdateDirective>...)` — Matcher<Stmt>

Would match a `#pragma omp target update ...` directive specifically.

**Not in clang-query 22** — trunk-only: the matcher was added to the reference after the LLVM 22 registry was frozen. The directive itself parses, and `isAllowedToContainClauseKind` singles it out because `to`/`from` clauses are allowed on no other directive in the sample:

```clang-query
match ompExecutableDirective(isAllowedToContainClauseKind("OMPC_to"))
```

**Expected:** 2 matches — `target update to(sum)` at `openmp.cpp:37`, `target update from(sum)` at `openmp.cpp:39`.

### `ompToClause(Matcher<OMPToClause>...)` — Matcher<OMPClause>

Would match the `to(...)` clause of a `target update`.

**Not in clang-query 22** — trunk-only, same reason as above. There is no clause-level substitute; the closest query is the directive-level one from `ompTargetUpdateDirective`, which finds both `target update` directives at `openmp.cpp:37` and `openmp.cpp:39`.

### `ompFromClause(Matcher<OMPFromClause>...)` — Matcher<OMPClause>

Would match the `from(...)` clause of a `target update`.

**Not in clang-query 22** — trunk-only; use the directive-level query shown under `ompTargetUpdateDirective`.

### `ompSplitDirective(Matcher<OMPSplitDirective>...)` — Matcher<Stmt>

Would match `#pragma omp split ...`, an OpenMP 6.0 loop-transformation
directive.

**Not in clang-query 22** — trunk-only, and Clang 22 does not parse the `split` directive at all, so there is no node to target and no alternative query.

### `ompCountsClause(Matcher<OMPCountsClause>...)` — Matcher<OMPClause>

Would match the `counts(...)` clause of `#pragma omp split`.

**Not in clang-query 22** — trunk-only, and the directive that carries it is unparsed in Clang 22; no alternative.

---

## 11.5 — CUDA

**Sample:** `manifests/cuda.cu` · flags: `-x cuda --cuda-host-only -nocudainc -nocudalib`

```bash
$LLVM/bin/clang-query manifests/cuda.cu -- -x cuda --cuda-host-only -nocudainc -nocudalib
```

CUDA adds exactly one node the reference cares about: the kernel launch
`kernel<<<grid, block>>>(args)`, a `CUDAKernelCallExpr`. It is a `CallExpr`
subclass, so `callee`, `hasArgument` and `argumentCountIs` work on it, and a
plain `callExpr()` matches it too. The launch configuration is lowered to a
call of `cudaConfigureCall`, which the SDK normally declares; the sample
declares it (and `dim3`) by hand, so `--cuda-host-only -nocudainc
-nocudalib` parses with no SDK installed.

### `cudaKernelCallExpr(Matcher<CUDAKernelCallExpr>...)` — Matcher<Stmt>

Matches a `<<<...>>>` kernel launch.

```clang-query
match cudaKernelCallExpr()
```

**Expected:** 2 matches — `scale<<<4, 64>>>(data, 2)` at `cuda.cu:37`, `fill<<<dim3(2, 2), dim3(8, 8), 0>>>(data)` at `cuda.cu:38`.

Narrow by the kernel being launched or by its arguments, exactly as with a
call:

```clang-query
match cudaKernelCallExpr(callee(functionDecl(hasName("scale"))))
```

**Expected:** 1 match — `cuda.cu:37`.

```clang-query
match cudaKernelCallExpr(hasArgument(1, integerLiteral(equals(2))))
```

**Expected:** 1 match — `scale<<<4, 64>>>(data, 2)` at `cuda.cu:37`.

The kernels themselves are ordinary functions carrying a `global`
attribute; `hasAttr` from Part 5 finds them:

```clang-query
match functionDecl(hasAttr("attr::CUDAGlobal"))
```

**Expected:** 2 matches — `scale` at `cuda.cu:28`, `fill` at `cuda.cu:34`.

---

## 11.6 — Blocks

**Sample:** `manifests/blocks.cpp` · flags: `-std=c++23 -fblocks`

```bash
$LLVM/bin/clang-query manifests/blocks.cpp -- -std=c++23 -fblocks
```

A block literal `^(int p) { ... }` produces two nodes at the same location:
a `BlockExpr` (the expression you can pass around) that owns a `BlockDecl`
(the body with its parameters, much like a lambda's call operator). The
type of a block is a `BlockPointerType`, spelled `int (^)(int)`, whose
pointee is always a function type, wrapped in a `ParenType` because of the
`(^...)` spelling.

```
   int (^twice)(int) = ^(int p) { return p * 2; };
        │                │
        │                └── BlockExpr ─owns─▶ BlockDecl(params: p)
        └── VarDecl of BlockPointerType ─pointee─▶ ParenType ─▶ FunctionProtoType
```

### `blockDecl(Matcher<BlockDecl>...)` — Matcher<Decl>

The declaration side of a block: parameters, body, captures.

```clang-query
match blockDecl()
```

**Expected:** 4 matches — the blocks at `blocks.cpp:10`, `blocks.cpp:11`, `blocks.cpp:13` and the empty `^{}` at `blocks.cpp:15`.

### `blockExpr(Matcher<BlockExpr>...)` — Matcher<Stmt>

The expression side, one per literal, at the same locations.

```clang-query
match blockExpr()
```

**Expected:** 4 matches — the same four literals.

Blocks capture variables like lambdas do; a captured `seed` is still a
`declRefExpr` inside the body:

```clang-query
match blockExpr(hasDescendant(declRefExpr(to(varDecl(hasName("seed"))))))
```

**Expected:** 1 match — the block passed to `runOp` at `blocks.cpp:13`.

### `blockPointerType(Matcher<BlockPointerType>...)` — Matcher<Type>

The type of a block, `R (^)(Args)`. Types print no location; wrap in a
declaration matcher to see users.

```clang-query
match blockPointerType()
```

**Expected:** 3 matches — the types of `IntOp`, `Callback` and `int (^twice)(int)`.

```clang-query
match typedefDecl(hasType(blockPointerType()))
```

**Expected:** 2 matches — `IntOp` at `blocks.cpp:3`, `Callback` at `blocks.cpp:4`.

### `pointee(Matcher<Type>)` — Matcher<BlockPointerType>, Matcher<ObjCObjectPointerType>

The pointed-to type, as for `pointerType` in Part 10. For a block pointer it
is a `ParenType` around the function type, so reach the prototype through
`ignoringParens`. For an Objective-C object pointer it is the interface
type.

```clang-query
match blockPointerType(pointee(parenType()))
```

**Expected:** 3 matches — every block pointer type in the file.

```clang-query
match typedefDecl(hasType(blockPointerType(
  pointee(ignoringParens(functionProtoType(parameterCountIs(2)))))))
```

**Expected:** 1 match — `Callback` at `blocks.cpp:4`.

```clang-query
# sample: manifests/objc.m -fobjc-exceptions
match varDecl(hasType(objcObjectPointerType(pointee(asString("Foo")))))
```

**Expected:** 2 matches — `Foo *f` at `objc.m:55` and the parameter `Foo *foo` at `objc.m:95`.

---

## 11.7 — Checkpoint

| Concept | What You Proved |
|---------|-----------------|
| Flags create the nodes | `-fopenmp`, `-fblocks`, `-x cuda` decide whether `omp*`, `block*`, `cuda*` matchers see anything. |
| ObjC declarations | Interface, implementation, category, protocol, ivar, property and method each have a node matcher; the class-hierarchy narrowers work on `@interface`. |
| Selectors | `hasSelector` is exact with colons, `matchesSelector` is a regex, `numSelectorArgs` counts colons, unary vs keyword vs (never) null. |
| Receivers | `hasReceiver` sees the instance expression only; `hasReceiverType` also reaches class messages via the interface type. |
| Messages are calls | `argumentCountIs`, `hasArgument`, `hasAnyArgument`, `callee` behave as on `callExpr`. |
| OpenMP clauses | `OMPClause` is never top-level: `ompDefaultClause` lives inside `hasAnyClause`; `isAllowedToContainClauseKind` takes `"OMPC_..."` strings. |
| Missing names | Five `omp*` names are trunk-only; directive-level queries stand in where a node exists. |
| CUDA | `cudaKernelCallExpr` is a `CallExpr`; the launch needs a hand-declared `cudaConfigureCall`. |
| Blocks | `blockExpr` owns `blockDecl`; `blockPointerType`'s pointee is a `ParenType` around the prototype. |

**Quiz.** In `objc.m`, find every *class* message whose selector takes
exactly one argument and that passes an `@"..."` literal as that argument.

> [!hint]- Hint
> Three narrowers/traversals inside one `objcMessageExpr(...)`: one for the
> kind of receiver, one that counts selector colons, one that looks at the
> arguments.

> [!success]- Answer
> `objcMessageExpr(isClassMessage(), numSelectorArgs(1), hasAnyArgument(objcStringLiteral()))` — 1 match, `[Foo fooWithName:@"fresh"]` at `objc.m:102`.

---

[← Part 10 — Traversal Matchers III — Types, TypeLocs & Templates](part_10_traversal_types_templates.md) | [Part 12 — Capstone — Real Checks in Pure clang-query →](part_12_capstone.md)
