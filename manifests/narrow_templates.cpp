// narrow_templates.cpp — Part 7.3 sample: templates, instantiations, dependence
// Run: $LLVM/bin/clang-query manifests/narrow_templates.cpp -- -std=c++23

int m = 0;

// ---- class templates ----------------------------------------------------
template <typename T> class X {};
class A {};
X<A> xa;                        // implicit instantiation X<A>
template <> class X<int> {};    // explicit specialization
X<int> xi;

// ---- function templates -------------------------------------------------
template <typename T> void generic(T t) { T i = t; m += 1; }
template <> void generic(int n) { m = n; }     // explicit specialization generic<int>
void call_generic() { generic(0U); generic(1.5); }

// ---- variable templates -------------------------------------------------
template <typename T> T zero = T(0);
template <> char zero<char> = 'z';
int uses_zero = zero<int> + zero<char>;

// ---- dependence ---------------------------------------------------------
template <typename T> void add(T x, int y) {
  int r = x + y;
  unsigned long n = sizeof(sizeof(T() + T()));
}
template <int Size> int size_of() { return Size; }

template <class T> class Derived : T { void f() { T::v; } };
template <typename T> struct Importer { typedef typename T::type dependent_name; };

// ---- integral template arguments ---------------------------------------
template <int N> struct Count {};
Count<42> c42;
