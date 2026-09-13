// manifests/trav_types.cpp — sample for Part 10 (Traversal III: Types, TypeLocs & Templates)
// flags: -std=c++23   (no #include; the VLA below is a Clang extension in C++)
#pragma clang diagnostic ignored "-Wvla-cxx-extension"

// ---- 10.1 hasType: one class, its sugar, and every place a type is "had" ----
class X {};
typedef X XAlias;                     // TypedefType sugar over X
typedef int Int;
XAlias aliased;                       // varDecl whose written type is the alias
struct Base {};
struct Derived : public virtual Base {};   // CXXBaseSpecifier has a type
class Y { friend class X; };          // FriendDecl naming a type
void useX(X &x) { (void)x; X z; }     // expr 'x' has type X&; 'z' has type X
typedef int &int_ref;
int seed = 1;
int_ref seedRef = seed;               // canonical type is int&, written type is a typedef

// ---- 10.2 hasDeclaration: from a node to the decl behind it --------------
enum Color { Red, Green };
Color color = Green;                  // EnumType + DeclRefExpr to an enumerator
struct Node {
  int   value;
  Node *next;
  Node *self() { return this; }
};
Node node{1, nullptr};
int  readValue() { return node.value; }          // MemberExpr -> fieldDecl
Node *make()      { return new Node{2, nullptr}; } // CXXNewExpr -> operator new
void copyNode()   { Node local(node); (void)local; } // CXXConstructExpr -> copy ctor
int  callIt()     { return readValue(); }          // CallExpr -> functionDecl

int jumpAround(int n) {
  void *target = &&done;              // AddrLabelExpr -> LabelDecl
  if (n > 0) goto *target;
  n = -n;
done:                                 // LabelStmt -> LabelDecl
  return n;
}

template <typename T> struct Wrap {
  T held;                             // TemplateTypeParmType -> TemplateTypeParmDecl
  Wrap take(Wrap other);              // InjectedClassNameType -> the template's pattern
};
Wrap<int> wrapped;                    // TemplateSpecializationType -> the specialization

template <typename T> struct Inherit : T {
  using typename T::type;             // UnresolvedUsingTypenameDecl
  type field;                         // UnresolvedUsingType -> that using decl
};

namespace lib { struct Widget {}; int helper(); }
using lib::Widget;                    // UsingShadowDecl for the type
using lib::helper;                    // UsingShadowDecl for the function
Widget widget;                        // UsingType -> the using-shadow
int viaUsing = helper();              // DeclRefExpr through the using decl

// ---- 10.3 pointers, references, arrays, and other one-level type sugar ----
int  *ip  = &seed;
int const *cip = &seed;
float const *cfp = nullptr;
int  &iref = seed;
int  Node::*fieldPtr = &Node::value;  // MemberPointerType, pointee int
int  arr[3];
int  *parr[3];
_Complex float cplx;
_Atomic(int)   atomInt;
_Atomic(float) atomFloat;
void vla(int b) { int a[b]; (void)a; }        // VariableArrayType with size expr 'b'
void decays(int param[]) { param[0] = 0; }    // 'param' has a DecayedType
auto deducedInt    = 1;
auto deducedDouble = 2.0;
int (*ptrToArray)[4];                 // ParenType wrapping an array
int (*ptrToFunc)(int);                // ParenType wrapping a function
template <typename T> double F(T t) { return 0; }
double fj = F(seed);                  // F<int>: 't' has a SubstTemplateTypeParmType
namespace N { namespace M { class D {}; } }
N::M::D d;                            // qualified type: NestedNameSpecifier N::M::
decltype(1)   dl = 1;
decltype(2.0) dd = 2.0;

// ---- 10.4 TypeLocs: types plus where they were written ---------------------
int  retInt()  { return 5; }
void retVoid() {}
struct Foo {
  int m;
  Foo() : m(0) {}
  Foo(int, int);
};
struct Sub : Base { Sub() : Base() {} };   // CXXCtorInitializer with a written type
auto tmpInt = int(3);                 // CXXFunctionalCastExpr
auto tmpFoo = Foo(1, 2);              // CXXTemporaryObjectExpr
template <typename T> T build() { return T(1); }  // CXXUnresolvedConstructExpr
struct Point { int px, py; };
Point pt = (Point){1, 2};             // CompoundLiteralExpr
long widened = (long)seed;            // CStyleCastExpr (an ExplicitCastExpr)
double implicitD = seed;              // ImplicitCastExpr int -> double
int *const pconst = &seed;            // QualifiedTypeLoc over a PointerTypeLoc
const int cy = 2;                     // QualifiedTypeLoc over a builtin
int &xx = seed;                       // ReferenceTypeLoc, referent int

// ---- 10.5 nested-name specifiers -------------------------------------------
struct A { struct B { struct C {}; }; };
A::B::C abc;
namespace ns { struct S {}; }
ns::S nss;

// ---- 10.6 template arguments -------------------------------------------------
template <typename T, typename U> class Pair {};
Pair<double, int> pdi;
Pair<int, double> pid;
template <typename T> class Vec {};
template <> class Vec<double> {};     // explicit specialization
Vec<int> vi;
template <typename T> void tf() {}
template <> void tf<double>() {}     // explicit specialization: <double> written on the decl
void callTf() { tf<int>(); }          // DeclRefExpr with explicit <int>
template <typename T, unsigned Nn, unsigned Mm> struct Matrix {};
constexpr unsigned R = 2;
Matrix<int, R * 2, R * 4> mat;        // expression template arguments
template <typename T, typename U> void fwd(T t, U u) {}
bool Bflag = false;
void callFwd() { fwd(R, Bflag); }     // deduces fwd<unsigned, bool>
struct Rec { int next; };
template <int(Rec::*next_ptr)> struct Chain {};
Chain<&Rec::next> chain;              // declaration template argument
template <int Tv> struct Const {};
Const<42> c42;                        // integral template argument
template <template <typename> class S> class Holder {};
Holder<Vec> hv;                       // template template argument
template <typename T> constexpr T zero = T(0);
template <> constexpr double zero<double> = 0.5;   // explicit variable specialization
int zi = zero<int>;                   // implicit VarTemplateSpecializationDecl zero<int>
template <typename T> void over(T);
template <typename T> void over(T, T);
template <typename T> void useOver() { over<T>(1); }  // OverloadExpr with <T>
