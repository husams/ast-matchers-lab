// narrow_decls.cpp — sample for Part 5 (Narrowing Matchers I — Logic & Declarations)
// Parse with:  $LLVM/bin/clang-query manifests/narrow_decls.cpp -- -std=c++23

// ---- 5.2 names & linkage ---------------------------------------------------
namespace geo {
namespace shapes {
struct Circle {};
struct Square {};
}  // namespace shapes
struct Circle {};   // geo::Circle — a different class from geo::shapes::Circle
}  // namespace geo
struct Circle {};   // ::Circle

int global_counter = 0;
static int file_counter = 0;

namespace {
void helper() {}
}  // namespace

// ---- 5.3 access, namespaces, attributes ------------------------------------
class Account {
 public:
  int id;
 protected:
  int balance;
 private:
  int pin;
};

struct Base {};
struct PublicChild : public Base {};
struct ProtectedChild : protected Base {};
class PrivateChild : Base {};            // 'class' => private inheritance by default
struct VirtualChild : virtual Base {};

namespace std {
inline namespace __1 {
class vector {};
namespace experimental {
class vector {};
}  // namespace experimental
}  // inline namespace __1
}  // namespace std

namespace outer {
inline namespace v2 {
struct Widget {};
}  // inline namespace v2
namespace {
struct Widget {};
}  // namespace
}  // namespace outer

[[deprecated("use new_api")]] void old_api();
void new_api();

// ---- 5.4 functions ----------------------------------------------------------
void declared_only();
void defined() {}
inline void inlined() {}
constexpr int square(int x) { return x * x; }
consteval int cube(int x) { return x * x * x; }
void erased() = delete;
extern "C" void c_entry() {}
extern "C" { void c_other() {} }
[[noreturn]] void die();
void may_throw();
void no_throw() noexcept;
void no_throw_true() noexcept(true);
void old_style() throw();
void may_throw_false() noexcept(false);
static void file_local() {}
void printf_like(const char* fmt, ...);
__attribute__((weak)) void weak_symbol();
void one(int a);
void two(int a, int b);
void three(int a, int b, int c) {}
auto trailing() -> int { return 0; }
int main() { return 0; }

// ---- 5.5 methods ------------------------------------------------------------
struct Shape {
  virtual ~Shape() = default;
  virtual double area() const = 0;
  virtual void draw();
  void name() const;
  void reset();
  Shape& operator=(const Shape&);
  Shape& operator=(Shape&&);
  int scale(this Shape& self, int k);
};
struct Rect : Shape {
  double area() const override { return 0; }
  void draw() final;
};
struct Sealed final : Rect {};

// ---- 5.6 constructors, conversions, ctor-initializers ------------------------
struct Point {
  int x, y;
  Point();                                          // default ctor
  Point(const Point&);                              // copy ctor
  Point(Point&&);                                   // move ctor
  explicit Point(int v);                            // explicit
  Point(int a, int b) : x(a), y(b) {}               // written member initializers
  Point(double d) : Point(static_cast<int>(d)) {}   // delegating
  explicit(false) Point(bool b);
  explicit(true) Point(char c);
  operator int() const;
  explicit operator bool() const;
};
Point::Point() : Point(0, 0) {}                     // delegating, out of line

template <class T>
struct Box {
  T value;
  Box(T v);
};
Box(int) -> Box<int>;
explicit Box(double) -> Box<double>;

struct Point3D : Point {
  int z;
  Point3D() : Point(), z(0) {}     // written base init + member init
  Point3D(int v) : z(v) {}         // base init added by the compiler
  using Point::Point;              // inheriting constructors
};

// ---- 5.7 records & tags -----------------------------------------------------
class Defined {};
class Forward;
struct Animal {};
struct Mammal : Animal {};
struct Dog : Mammal {};
union Number { int i; float f; };
enum Color { Red, Green };
enum class Level { Low, High };
auto lambda = [] { return 42; };

// ---- 5.8 variables, fields, params -----------------------------------------
int g_plain = 1;
static int g_static = 2;
extern int g_extern;
thread_local int g_thread = 3;
constinit int g_constinit = 4;
constexpr int g_constexpr = 5;
inline int g_inline = 6;
extern "C" int g_cvar = 7;

void storage_demo() {
  int local = 0;
  static int local_static = 0;
  thread_local int local_thread = 0;
  try {
  } catch (int caught) {
  }
  auto cap = [captured = local] { return captured; };
}

struct Flags {
  int a : 2;
  int b : 4;
  int c : 2;
  int plain;
};

void with_default(int val, int mode = 0);
void positional(int first, int second, int third);

// ---- 5.1 / 5.9 statements and implicit nodes ------------------------------
void branches(int n) {
  if (true) {}
  for (; true;) {}
  while (true) {}
  if constexpr (sizeof(int) == 4) {}
  if consteval {}
}

struct Outer {
  struct Inner {} inner;
} nested = {};

void captures() {
  int i = 1, j = 2;
  auto l = [&, j]() { return i + j; };
}
