// Part 2 sample: one of (almost) every declaration kind, no #include.
// Parse with:  clang-query manifests/decls.cpp -- -std=c++23

// ---- 2.1 root & generic declarations -----------------------------------
namespace geo {
int origin = 0;
void reset();
struct Point { int x; int y; };
}  // namespace geo

typedef int Integer;
static_assert(sizeof(int) == 4, "int is 32-bit");
__asm("nop");

// ---- 2.2 functions, parameters & methods --------------------------------
void free_function(int count, double scale);

class Shape {
public:
  Shape() : sides_(0) {}
  Shape(int sides) : sides_(sides), name_("shape") {}
  virtual ~Shape() {}
  int area() const;
  operator bool() const;
  [[nodiscard]] int corners() const;
private:
  int sides_;
  const char* name_;
};

int Shape::area() const { return sides_ * sides_; }

// ---- 2.3 records, fields & friends --------------------------------------
class Circle : public virtual Shape {};
struct Square : Circle {};

struct Packet {
  union { int code; float ratio; };
  int len;
};

class Vault {
  friend void peek(const Vault&);
  friend class Auditor;
  int secret_;
};

struct Pair { int first; int second; };
int use_bindings() {
  Pair p{1, 2};
  auto [first, second] = p;
  return first + second;
}

// ---- 2.4 templates & concepts -------------------------------------------
template <typename T, typename U, int I>
class Grid {};
template <typename T, int I>
class Grid<T, T*, I> {};
template <>
class Grid<int, int, 1> {};
Grid<char, char, 2> grid;

template <typename T> T twice(T v) { return v + v; }

template <typename T> struct Box { Box(T); T value; };
Box(int) -> Box<int>;

template <template <typename> class Container, typename Elem, int Cap>
struct Bag {};

template <typename T> concept Small = sizeof(T) <= 4;
template <typename T> concept Dereferenceable = requires(T p) { *p; };

template <typename Base>
struct Derived : private Base {
  using typename Base::value_type;
  using Base::size;
};

// ---- 2.5 enums, aliases & the using family ------------------------------
enum Color { Red, Green, Blue };
enum class Mode : unsigned char { Fast, Safe };

using Real = double;
template <typename T> using Ptr = T*;

using geo::origin;
Mode alias_demo() {
  using namespace geo;
  using enum Mode;
  reset();
  return Fast;
}

// ---- 2.6 namespaces, linkage & odds and ends ----------------------------
namespace {}
namespace g = geo;
extern "C" {
void c_entry();
}
extern "C" int c_var;

int countdown(int n) {
again:
  if (n > 0) { --n; goto again; }
  return n;
}

// ---- 2.7 non-Decl nodes: attributes, bases, initializers, captures ------
struct [[nodiscard]] Result {};
void take(int* p __attribute__((nonnull)));

int capture_demo() {
  int x = 1;
  auto by_value = [x]() { return x; };
  auto init_cap = [y = x]() { return y; };
  return by_value() + init_cap();
}

namespace tags {
class X;
template <class T> class Z {};
struct S {};
union U {};
enum E { A, B, C };
void F();
}  // namespace tags
