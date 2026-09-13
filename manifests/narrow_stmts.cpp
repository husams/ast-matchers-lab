// narrow_stmts.cpp — sample for Part 6 (narrowing matchers on statements
// and expressions). No #include; parses with -std=c++23 and zero diagnostics.

// --- hand-written std::strong_ordering so `<=>` works without <compare> ---

namespace std {
struct strong_ordering {
  int bits; // bit 1 = less, bit 2 = equal, bit 4 = greater
  friend constexpr bool operator==(strong_ordering a, int) { return a.bits & 2; }
  friend constexpr bool operator<(strong_ordering a, int) { return a.bits & 1; }
  friend constexpr bool operator>(strong_ordering a, int) { return a.bits & 4; }
  friend constexpr bool operator<=(strong_ordering a, int) { return a.bits & 3; }
  friend constexpr bool operator>=(strong_ordering a, int) { return a.bits & 6; }
};
} // namespace std

// --- 6.1 operators ---------------------------------------------------------

struct Vec2 {
  double x;
  double y;
  Vec2() = default;
  Vec2(const Vec2 &) = default;
  Vec2 &operator=(const Vec2 &o);
  Vec2 &operator+=(const Vec2 &o);
  bool operator<(const Vec2 &o) const;
  bool operator==(const Vec2 &o) const;
  double operator*(const Vec2 &o) const;
  Vec2 operator-() const;
  double operator[](int i) const;
};
Vec2 operator+(Vec2 a, const Vec2 &b);

struct Log {};
Log &operator<<(Log &l, int v);

struct Version {
  int major;
  int minor;
  bool operator==(const Version &o) const;
  std::strong_ordering operator<=>(const Version &o) const;
};

int builtin_ops(int a, int b) {
  int r = 0;
  r = a + b;
  r += a * b;
  r -= b;
  bool eq = (a == b);
  bool lt = (a < b);
  bool ge = (a >= b);
  bool both = eq && lt;
  bool nope = !both;
  int neg = -a;
  ++r;
  r--;
  int *p = &r;
  return *p + ge;
}

double overloaded_ops(Vec2 v1, Vec2 v2, Log &log) {
  v1 = v2;
  v1 += v2;
  bool lt = v1 < v2;
  bool eq = v1 == v2;
  double dot = v1 * v2;
  Vec2 sum = v1 + v2;
  Vec2 flipped = -sum;
  log << 7;
  return dot + v1[0];
}

bool rewritten_ops(Version a, Version b) {
  bool lt = a < b;
  bool gt = a > b;
  bool le = a <= b;
  bool ne = a != b;
  auto ord = a <=> b;
  return lt || gt || le || ne || (ord < 0);
}

template <typename... Args>
auto sum(Args... args) {
  return (0 + ... + args); // binary left fold
}
template <typename... Args>
auto product(Args... args) {
  return (args * ... * 1); // binary right fold
}
template <typename... Args>
bool all_of(Args... args) {
  return (args && ...); // unary right fold
}
template <typename... Args>
bool any_of(Args... args) {
  return (... || args); // unary left fold
}

// --- 6.2 literals ----------------------------------------------------------

void literals() {
  bool t = true;
  bool f = false;
  char a = 'a';
  char nul = '\0';
  double pi = 3.14;
  double e = 2.718;
  float half = 0.5f;
  int answer = 42;
  int zero = 0;
  int minus = -13;
  long long big = 42LL;
  unsigned u = 7u;
}

void null_constants(int i) {
  void *v2 = nullptr;
  void *v3 = __null;
  char *cp = (char *)0;
  int *ip = 0;
  int n = 0;
  int *notnull = &i;
}

// --- 6.3 calls & construction ---------------------------------------------

void f2(int x, int y);
void f3(int x, int y, int z);
void fd(int x, int y = 0);

struct Pt {
  Pt();
  Pt(int x);
  Pt(int x, int y);
};

struct Point {
  double x;
  double y;
};

void calls_and_ctors() {
  f2(0, 0);
  f3(0, 0, 0);
  fd(1);
  Pt a;
  Pt b(1);
  Pt c(1, 2);
  Pt d{3, 4};
  Pt e = {5, 6};
  Point origin = Point(); // value-init: zero-initialization required
}

namespace NS {
struct X {};
void y(X);
} // namespace NS
void y(...);

void adl_test() {
  NS::X x;
  y(x);     // found by ADL only
  NS::y(x); // qualified: no ADL
  y(42);    // ordinary lookup
}

void news() {
  int *many = new int[10];
  int *one = new int(5);
  Pt *pts = new Pt[3];
}

// --- 6.4 casts -------------------------------------------------------------

void casts(int n, double d) {
  double widened = n;                  // CK_IntegralToFloating
  int narrowed = d;                    // CK_FloatingToIntegral
  long lg = static_cast<long>(n);      // CK_IntegralCast
  float fl = d;                        // CK_FloatingCast
  int *ip = 0;                         // CK_NullToPointer
  void *vp = &n;                       // CK_BitCast
}

// --- 6.5 members & names (dependent code) -----------------------------------

template <typename T>
struct Box {
  T value;
  void reset();
};

template <typename T>
void use_box(Box<T> b, Box<T> *p) {
  b.reset();
  p->reset();
  b.value = T();
  Box<T> c(T(1, 2));
}

struct Printer {
  int width;
  void print(int);
  void print(double);
  template <typename T>
  void emit(T v) {
    this->print(v);
    print(v);
  }
  int self() { return this->width + width; }
};

int plain_members(Printer &pr, Printer *pp) { return pr.width + pp->width; }

// --- 6.6 statements --------------------------------------------------------

void bodies() {
  {
  }
  {
    int a, b;
    int c;
    int d = 2, e;
  }
}

int catches() {
  try {
    return 1;
  } catch (int) {
    return 2;
  } catch (...) {
    return 3;
  }
}

// --- 6.7 lambdas -----------------------------------------------------------

struct Counter {
  int count;
  int f() {
    auto explicit_this = [this]() { return count; };
    auto by_ref = [&]() { return count; };
    int local = 1;
    auto no_this = [local]() { return local; };
    return explicit_this() + by_ref() + no_this();
  }
};

// --- 6.8 sizeof / alignof --------------------------------------------------

int traits() {
  int x;
  int s = sizeof(x) + alignof(int) + sizeof(double);
  return s;
}
