# Lab Progress

Mark each section `[x]` as you complete it.

## Part 1 — clang-query & the DSL Grammar
- [ ] 1.1 — Why a matcher DSL
- [ ] 1.2 — Starting clang-query
- [ ] 1.3 — The three matcher categories
- [ ] 1.4 — Match output
- [ ] 1.5 — `let` and query files
- [ ] 1.6 — Traversal modes
- [ ] 1.7 — Children, descendants, and the logical matchers
- [ ] 1.8 — How to read a reference entry
- [ ] 1.9 — Checkpoint

## Part 2 — Node Matchers I — Declarations
- [ ] 2.1 — The Root and the Generic Declaration Matchers
- [ ] 2.2 — Functions, Parameters and Methods
- [ ] 2.3 — Records, Fields and Friends
- [ ] 2.4 — Templates and Concepts
- [ ] 2.5 — Enums, Aliases and the `using` Family
- [ ] 2.6 — Namespaces, Linkage and Variables
- [ ] 2.7 — Non-`Decl` Nodes That Live Beside Declarations
- [ ] 2.8 — Checkpoint

## Part 3 — Node Matchers II — Statements & Expressions
- [ ] 3.1 — Statements: blocks, control flow, jumps, exceptions
- [ ] 3.2 — Literals and initializers
- [ ] 3.3 — Names and members
- [ ] 3.4 — Operators
- [ ] 3.5 — Calls, construction and lambdas
- [ ] 3.6 — Casts
- [ ] 3.7 — Invisible nodes: temporaries, cleanups and helpers
- [ ] 3.8 — Dependent and template nodes
- [ ] 3.9 — Coroutines
- [ ] 3.10 — Exotic C and GNU extensions
- [ ] 3.11 — Checkpoint

## Part 4 — Node Matchers III — Types & TypeLocs
- [ ] 4.1 — The Three Roots: `type`, `qualType`, `typeLoc`
- [ ] 4.2 — Builtin Types, Pointers, References
- [ ] 4.3 — Arrays
- [ ] 4.4 — Function Types
- [ ] 4.5 — Records, Enums, Tags
- [ ] 4.6 — Sugar: typedef, using, parentheses, macros
- [ ] 4.7 — Templates in Types
- [ ] 4.8 — `auto`, `decltype`, transforms, atomic, complex
- [ ] 4.9 — TypeLocs
- [ ] 4.10 — Nested Name Specifiers, Template Arguments, Template Names
- [ ] 4.11 — Checkpoint

## Part 5 — Narrowing Matchers I — Logic & Declarations
- [ ] 5.1 — Logical combinators
- [ ] 5.2 — Names and linkage
- [ ] 5.3 — Access, namespaces and attributes
- [ ] 5.4 — Functions
- [ ] 5.5 — Methods
- [ ] 5.6 — Constructors, conversions and initializers
- [ ] 5.7 — Records and tags
- [ ] 5.8 — Variables, fields and parameters
- [ ] 5.9 — Implicit nodes
- [ ] 5.10 — Checkpoint

## Part 6 — Narrowing Matchers II — Statements & Expressions
- [ ] 6.1 — Operators
- [ ] 6.2 — Literals
- [ ] 6.3 — Calls & construction
- [ ] 6.4 — Casts
- [ ] 6.5 — Members & names
- [ ] 6.6 — Statements
- [ ] 6.7 — Lambdas
- [ ] 6.8 — sizeof / alignof kind
- [ ] 6.9 — Checkpoint

## Part 7 — Narrowing Matchers III — Types, Templates & Source Locations
- [ ] 7.1 — QualType predicates
- [ ] 7.2 — Sizes: arrays and string literals
- [ ] 7.3 — Templates & dependence
- [ ] 7.4 — Source locations & macros
- [ ] 7.5 — Bound-node equality
- [ ] 7.6 — Checkpoint

## Part 8 — Traversal Matchers I — Tree Navigation & Declarations
- [ ] 8.1 — The generic tree walkers
- [ ] 8.2 — Functions
- [ ] 8.3 — Methods & records
- [ ] 8.4 — Constructors
- [ ] 8.5 — Variables, fields & bindings
- [ ] 8.6 — Contexts & using
- [ ] 8.7 — Checkpoint

## Part 9 — Traversal Matchers II — Statements & Expressions
- [ ] 9.1 — Calls
- [ ] 9.2 — Operators
- [ ] 9.3 — Control flow
- [ ] 9.4 — Declarations inside statements
- [ ] 9.5 — The `ignoring*` family
- [ ] 9.6 — Casts
- [ ] 9.7 — `new`, `delete` & initializer lists
- [ ] 9.8 — Lambdas
- [ ] 9.9 — `sizeof` / `alignof`
- [ ] 9.10 — Checkpoint

## Part 10 — Traversal Matchers III — Types, TypeLocs & Templates
- [ ] 10.1 — `hasType`: the workhorse
- [ ] 10.2 — `hasDeclaration`: from a node to the decl behind it
- [ ] 10.3 — Pointers, references, arrays & one-level sugar
- [ ] 10.4 — TypeLocs: type + where it was written
- [ ] 10.5 — Nested-name specifiers
- [ ] 10.6 — Template arguments
- [ ] 10.7 — Checkpoint

## Part 11 — Objective-C, OpenMP, CUDA & Blocks
- [ ] 11.1 — Why these rows exist
- [ ] 11.2 — Objective-C declarations
- [ ] 11.3 — Objective-C statements & messages
- [ ] 11.4 — OpenMP
- [ ] 11.5 — CUDA
- [ ] 11.6 — Blocks
- [ ] 11.7 — Checkpoint

## Part 12 — Capstone — Real Checks in Pure clang-query
- [ ] 12.1 — modernize-use-nullptr
- [ ] 12.2 — modernize-use-override
- [ ] 12.3 — readability-container-size-empty
- [ ] 12.4 — bugprone-assignment-in-if-condition & self-assignment
- [ ] 12.5 — performance-unnecessary-value-param (approximated)
- [ ] 12.6 — non-virtual destructor in a polymorphic class
- [ ] 12.7 — missing `default:` in a switch over an enum
- [ ] 12.8 — a macro-aware check
- [ ] 12.9 — running scripts with `-f` and reading the output
- [ ] 12.10 — Appendix: reference names not registered in clang-query 22
- [ ] 12.11 — Checkpoint
