// Part 2 sample for exportDecl: a C++20 module interface unit.
// Parse with:  clang-query manifests/decls_module.cppm -- -std=c++23
export module shapes;

export void foo();
export { int v; }
export namespace detail { void bar(); }
