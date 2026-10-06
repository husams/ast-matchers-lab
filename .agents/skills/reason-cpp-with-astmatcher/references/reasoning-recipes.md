# C++ reasoning recipes

## Contents

- [Declarations and class use](#declarations-and-class-use)
- [Call relationships](#call-relationships)
- [Local variables and references](#local-variables-and-references)
- [Fields and signatures](#fields-and-signatures)
- [Chained investigations](#chained-investigations)
- [Evidence limits](#evidence-limits)

Run these expression-preparation examples with `uv run python` in the deployed
project. They prepare SDK expressions for `MatcherQuery.matches`; they do not
inspect source on their own. Pass the prepared expressions to the uv-launched
API examples in [API reference](api-reference.md). Add a `match ` prefix only
for bridge scripts. Replace example qualified symbols with the user's targets.
Pass sequences such as `(expression,)`, not a single string. Check all runtime
diagnostics and truncation as instructed in the main skill.

## Declarations and class use

Find a class definition:

```bash
uv run python - <<'PY'
expression = (
    'cxxRecordDecl(isDefinition(), unless(isImplicit()), '
    'hasName("::app::Service")).bind("record")'
)
print(expression)
PY
```

Run `inspect_record()` on the returned binding to enumerate members, base
classes, and supported method edges without reading the class file. Preserve
`record_identity` for template specializations; choose `AsIs` if investigating
generated instantiations. A forward declaration alone does not establish that
the definition was parsed.

Find direct value variables of a record type:

```bash
uv run python - <<'PY'
expression = (
    'varDecl(hasType(cxxRecordDecl(hasName("::app::Service"))))'
    '.bind("object")'
)
print(expression)
PY
```

Find fields of that type and derived classes:

```bash
uv run python - <<'PY'
expressions = (
    'fieldDecl(hasType(cxxRecordDecl(hasName("::app::Service")))).bind("field")',
    'cxxRecordDecl(isDefinition(), unless(isImplicit()), '
    'isDerivedFrom("::app::Service")).bind("derived")',
)
print(expressions)
PY
```

Treat these type-use matchers as specific categories, not an exhaustive set of
all uses. Pointer/reference wrappers, aliases, template arguments, and method
calls can require additional type or expression matchers. Inspect returned
types and catalog overloads, then broaden deliberately. Use main-file filters
only if the user specifically asks about uses spelled in that CPP file.

## Call relationships

Bind each direct call, the resolved target declaration, and its enclosing
function in the same match:

```bash
uv run python - <<'PY'
expression = (
    'callExpr(callee(functionDecl(hasName("::app::Service::start"))'
    '.bind("callee")), forFunction(functionDecl().bind("caller")))'
    '.bind("call")'
)
print(expression)
PY
```

`functionDecl` includes methods. Narrow the callee with `cxxMethodDecl`,
parameter/return-type matchers, or `isConst()` when the user means a particular
overload. Inspect returned `signature` and `qualified_name` before combining
edges. A call in a global initializer has no enclosing function and will not
match this recipe; query `callExpr(callee(...)).bind("call")` separately if needed.

Enumerate direct callees in one function:

```bash
uv run python - <<'PY'
expression = (
    'callExpr(forFunction(functionDecl(hasName("::app::process"))'
    '.bind("caller")), callee(functionDecl().bind("callee"))).bind("call")'
)
print(expression)
PY
```

Use `forFunction` to select the semantic enclosing function instead of a broad
`hasAncestor(functionDecl(...))` that can associate a nested lambda's calls with
its outer function. Constructor invocations use `cxxConstructExpr`; they are
not included in this `callExpr` recipe. Indirect or dependent calls need separate
queries and cannot establish one concrete runtime target from this recipe.

Compose reusable callee matchers with SDK definitions:

```bash
uv run python - <<'PY'
from astmatcher_sdk import Definition

definitions = (
    Definition("target", 'functionDecl(hasName("::app::Service::start"))'),
    Definition("calls_target", 'callExpr(callee(target)).bind("call")'),
)
matches = ("calls_target",)
print(definitions, matches)
PY
```

These are reusable expressions, not a pipeline of captured nodes. A second
request must supply the definitions again. For workspace scans, bind the call
site and caller initially; rerun relevant TUs in file scope to retain callee
bindings from headers.

## Local variables and references

Bind a non-static local variable first and join its uses by declaration identity within
one matcher, so a same-name variable in a nested block cannot be mistaken for it:

```bash
uv run python - <<'PY'
expression = (
    'functionDecl(isDefinition(), hasName("::app::process"), '
    'forEachDescendant(varDecl(hasLocalStorage(), unless(parmVarDecl()), '
    'hasName("value"))'
    '.bind("variable")), '
    'forEachDescendant(declRefExpr(to(varDecl(equalsBoundNode("variable"))))'
    '.bind("reference"))).bind("function")'
)
print(expression)
PY
```

Read each match's `variable` and `reference` together. Multiple local
declarations called `value` produce separate identity-checked rows; distinguish
them by their returned declaration locations. Lexically nested lambda uses can
also appear. This recipe excludes parameters and static locals. Use
`parmVarDecl` for parameters or `isStaticLocal()` for static locals;
member accesses require `memberExpr`.

A variable with no references produces no row in the joined recipe. Run a
separate variable-declaration query before inferring that a declaration is
missing. To inspect a use as an argument, assignment, return, or dereference,
bind the surrounding expression in another composed query.

Do not describe these uses as reaching definitions or a value flowing through
multiple functions. Passing a variable to argument N proves a syntactic
argument association, not aliasing, mutation, execution, or the callee's effects.

## Fields and signatures

Bind a field declaration and its member-access expression:

```bash
uv run python - <<'PY'
expression = (
    'memberExpr(member(fieldDecl(hasName("::app::Service::state"))'
    '.bind("field"))).bind("access")'
)
print(expression)
PY
```

Refine with surrounding AST relationships to distinguish assignment sites
from other uses; do not label every member access a write. Read access control
and field-type relationships through `inspect_record()` when appropriate.

Find a particular callable shape:

```bash
uv run python - <<'PY'
expression = (
    'functionDecl(hasName("::app::process"), parameterCountIs(1), '
    'hasParameter(0, parmVarDecl(hasType(asString("int")))), '
    'returns(asString("bool"))).bind("function")'
)
print(expression)
PY
```

Prefer semantic type matchers when aliases or qualifiers matter. `asString`
compares Clang's printed type spelling; it is not a portable canonical-signature
comparison. Use returned signatures to explain overload differences and source
locations to distinguish redeclarations.

## Chained investigations

For “class defined and used in a CPP file, including method calls”:

1. Query explicit record definitions and inspect their returned member graph.
2. Query type uses and call sites, binding the use and relevant declaration.
3. Keep the TU and declaration file separate: a type may be defined in a header
   and used in the CPP file. Set `isExpansionInMainFile()` on use-site matchers
   only when that restriction is requested.
4. Correlate by qualified symbol, specialization/signature, and API evidence;
   label unresolved or ambiguous correlations rather than joining by bare name.

For “follow this value into another function”:

1. Bind the declaration and identity-checked references in the caller.
2. Match the selected reference in a call argument and bind the callee and call.
3. Query the callee's definition and relevant parameter references with the same
   build context, using the resolved callee's qualified name and signature.
4. Report the observed argument-to-parameter chain as structural evidence;
   state that runtime data-flow/alias proof is unavailable through these APIs.

For an API-returned text snippet that ends before the code of interest, query
smaller bound nodes under the same function/record instead of reading its file.
State the limitation if the required evidence still cannot be returned.

## Evidence limits

Carry query/TU context alongside every evidence row. Do not deduplicate two
template specializations solely because their source ranges coincide. Do not
collapse a caller/callee relation to a set of names before preserving call sites.
Do not treat zero matches as “unused” if declarations, headers, configurations,
or failed/truncated TUs were outside the checked scope. Report observations,
then clearly mark hypotheses that require CFG, runtime, or interprocedural proof.
