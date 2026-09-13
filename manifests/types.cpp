// manifests/types.cpp — sample for Part 4 (Types & TypeLocs)
// flags: -std=c++23   (no #include; VLAs are a Clang extension in C++)
#pragma clang diagnostic ignored "-Wvla-cxx-extension"

// ---- builtin types, pointers, references --------------------------------
int    i = 1;
float  f = 2.0f;
bool   b = true;
int   *p = &i;
int   &lr = i;
int  &&rr = 3;
auto  &ar = lr;       // deduced: int&
auto &&fr = rr;       // deduced: int&  (reference collapsing)
auto &&xr = 4;        // deduced: int&&

// ---- member pointers ---------------------------------------------------
struct A { int m; void method(); };
int A::*mp = &A::m;
void (A::*mfp)() = &A::method;

// ---- arrays -------------------------------------------------------------
int ca[2];
int ia[] = {2, 3};
void arrays(int param[]) {
  int va[ia[0]];      // variable-length array
  param[1] = 0;       // 'param' decays to int*
}

// ---- function types -----------------------------------------------------
int (*fp)(int);
void g();
void h(int) {}

// ---- records, enums, tags -----------------------------------------------
struct S {};
class  C {};
enum E { Green };
enum class SC { Red };
S s; C c; E e; SC sc;

// ---- sugar: typedef / using / paren / decayed / macro-qualified ---------
typedef int Int;
Int ti = 5;
namespace lib { struct T {}; }
using lib::T;
T ut;
int (*ptr_to_array)[4];
int *array_of_ptrs[4];
#define CDECL __attribute__((cdecl))
typedef void (CDECL *X)();
typedef void (__attribute__((cdecl)) *Y)();

// ---- auto / decltype / __underlying_type / atomic / complex -------------
auto n = 4;
decltype(i + f) result = i + f;
typedef __underlying_type(E) Under;
_Atomic(int)   ai;
_Complex float cf;

// ---- templates ----------------------------------------------------------
template <typename T, int Size>
struct Box {
  T    value;
  T    data[Size];                                       // dependent-sized array
  typedef T __attribute__((ext_vector_type(Size))) vec;  // dependent ext-vector
  void take(Box b);                                      // injected class name
  void takeSpec(Box<T, Size> b);                         // written specialization
};
template struct Box<int, 3>;   // explicit instantiation
Box<char, 2> box;              // implicit instantiation

template <typename T> struct Dep {
  typedef typename T::type dependent_name;               // dependent name
};

template <typename T> void F(T t) { int k = 1 + t; }
void callF() { F(1); }         // instantiates F<int>: 't' has a substituted type

template <typename T> class Ctad { public: Ctad(T); };
Ctad ct(123);                  // CTAD: deduced template specialization

template <typename> struct Wrap {};
template <template <typename> class TT> struct Holder {};
Holder<Wrap> holder;           // template template argument: a TemplateName

// ---- nested name specifiers ---------------------------------------------
namespace nn {
  struct Q { static void f(); };
  void Q::f() {}
  void call() { Q::f(); }
}
nn::Q q;
const int ci = 0;
