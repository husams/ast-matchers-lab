// trav_decls.cpp — sample for Part 8 (traversal matchers I: tree navigation
// and declarations). No #include; parses with -std=c++23, zero diagnostics.

// --- 8.1 tree walkers: nested records --------------------------------------
class X {};
class Y { class X {}; };
class Z { class Y { class X {}; }; };
class Deep { class B { class C { class D { class E {}; }; }; }; };

// --- 8.1 parent / ancestor on statements ----------------------------------
void ifHolder() { if (true) { int v = 42; } }
void loopHolder() { for (;;) { int v = 43; } }
long widened = 7;

// --- 8.1 eachOf / optionally ----------------------------------------------
class Pair { int first; int second; };
class Lone { int other; };

// --- 8.1 binaryOperation ---------------------------------------------------
struct Tag { bool operator!=(const Tag &) const; };
void plainCompare() { (void)(1 != 2); (void)(Tag() != Tag()); }
template <typename T> void templCompare() { (void)(1 != 2); (void)(T() != Tag()); }
struct HasOpEq { bool operator==(const HasOpEq &) const; };
void inverse() { HasOpEq s1; HasOpEq s2; if (s1 != s2) return; }
struct HasSpaceship { int operator<=>(const HasSpaceship &) const; };
void useSpaceship() { HasSpaceship s1; HasSpaceship s2; if (s1 < s2) return; }

// --- 8.1 invocation ---------------------------------------------------------
struct ConstructorTakesInt { ConstructorTakesInt(int i) {} };
void callTakesInt(int i) {}
void doCall() { callTakesInt(42); }
void doConstruct() { ConstructorTakesInt cti(42); }

// --- 8.2 functions ----------------------------------------------------------
void declaredTwice();
void declaredTwice() {}
void declaredOnce();
class Triple { void f(int x, int y, int z) {} };
template <bool b> struct Expl {
  Expl(int);                 // #1 no explicit
  explicit Expl(double);     // #2 plain explicit, no expression
  explicit(false) Expl(bool);
  explicit(true) Expl(char);
  explicit(b) Expl(long);
};

// --- 8.3 methods & records --------------------------------------------------
class Animal { public: virtual void speak(); };
class Dog : public Animal { void speak() override; };
class Puppy : public Dog { void speak() override; };
class Left { virtual void act(); };
class Right { virtual void act(); };
class Both : public Left, public Right { void act() override; };
class Widget { public: Widget(); void render(); };
Widget w = Widget();
class SpecialBase {};
class Proxy : SpecialBase {};
class IndirectlyDerived : Proxy {};
typedef SpecialBase SB1;
typedef SB1 SB2;
class ViaTypedef : public SB2 {};

// --- 8.4 constructor initializers -------------------------------------------
class Counter { Counter() : hits(0), misses(0) {} int hits; int misses; };

// --- 8.5 variables, fields, bindings ----------------------------------------
bool probe() { return true; }
bool flag = probe();
class Config { int a = 2; int b = 3; int c; };
void decompose() { int arr[3] = {1, 2, 3}; auto &[f, s, t] = arr; f = 42; }

// --- 8.6 contexts & using ---------------------------------------------------
namespace N { namespace M { class D {}; } }
namespace Lib { int counter; void helper(); }
using Lib::counter;
using Lib::helper;
namespace NF { template <class T> void fn(T t); }
template <class T> void callFn() { using NF::fn; fn(T()); }
