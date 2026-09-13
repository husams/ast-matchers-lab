// Sample for Part 3 — Node Matchers II — Statements & Expressions.
// No #include: every std:: facility used below is a hand-written stub.
// Compile check:  clang++ -std=c++23 -fsyntax-only manifests/stmts.cpp
//
// ---- minimal std stubs ----------------------------------------------------
namespace std {
template <class E> class initializer_list {
  const E *first;
  unsigned long count;
public:
  constexpr initializer_list() noexcept : first(nullptr), count(0) {}
  constexpr unsigned long size() const noexcept { return count; }
  constexpr const E *begin() const noexcept { return first; }
  constexpr const E *end() const noexcept { return first + count; }
};

struct strong_ordering {
  int value;
  static const strong_ordering less;
  static const strong_ordering equal;
  static const strong_ordering equivalent;
  static const strong_ordering greater;
  friend constexpr bool operator==(strong_ordering a, strong_ordering b) noexcept { return a.value == b.value; }
  friend constexpr bool operator==(strong_ordering a, int) noexcept { return a.value == 0; }
  friend constexpr bool operator<(strong_ordering a, int) noexcept { return a.value < 0; }
  friend constexpr bool operator>(strong_ordering a, int) noexcept { return a.value > 0; }
  friend constexpr bool operator<=(strong_ordering a, int) noexcept { return a.value <= 0; }
  friend constexpr bool operator>=(strong_ordering a, int) noexcept { return a.value >= 0; }
};
inline constexpr strong_ordering strong_ordering::less{-1};
inline constexpr strong_ordering strong_ordering::equal{0};
inline constexpr strong_ordering strong_ordering::equivalent{0};
inline constexpr strong_ordering strong_ordering::greater{1};

template <class R, class...> struct coroutine_traits {
  using promise_type = typename R::promise_type;
};
template <class P = void> struct coroutine_handle {
  constexpr coroutine_handle() noexcept = default;
  template <class U> constexpr coroutine_handle(coroutine_handle<U>) noexcept {}
  static coroutine_handle from_address(void *) noexcept { return {}; }
  void *address() const noexcept { return nullptr; }
  void resume() const {}
  void destroy() const {}
  bool done() const noexcept { return true; }
};
struct suspend_never {
  bool await_ready() const noexcept { return true; }
  void await_suspend(coroutine_handle<>) const noexcept {}
  void await_resume() const noexcept {}
};
} // namespace std

// ---- 3.1 statements ---------------------------------------------------------
int bar();
void statements(int a, int n) {
  int i = 0;                       // declStmt
  ;                                // nullStmt
  if (a > 0) { i = 1; } else { i = 2; }
  for (int k = 0; k < n; ++k) { if (k == 3) break; if (k == 1) continue; }
  while (i < 10) { ++i; }
  do { --i; } while (i > 0);
  int arr[] = {1, 2, 3};
  for (int e : arr) { i += e; }    // cxxForRangeStmt
  switch (a) {
  case 37: i = 37; break;
  default: i = 0; break;
  }
  goto done;
done:
  bar();
  asm volatile("nop");
}

int returns(int x) { return x + 1; }

void exceptions() {
  try { throw 5; } catch (int) { }
}

// ---- 3.2 literals -----------------------------------------------------------
constexpr unsigned long long operator""_kb(unsigned long long v) { return v * 1024; }
struct Point { int x, y; };
struct IntList { IntList(std::initializer_list<int>); };
void literals() {
  int dec = 7;
  long big = 7L;
  double d = 2.5;
  float f = 1.0f;
  char c = 'a';
  wchar_t wc = L'a';
  const char *s = "abcd";
  const wchar_t *ws = L"abcd";
  bool t = true;
  int *np = nullptr;
  double _Complex z = 1.0i;        // imaginaryLiteral (GNU)
  auto kb = 4_kb;                  // userDefinedLiteral
  Point p = {1, 2};                // initListExpr
  Point q = {.x = 3, .y = 4};      // designatedInitExpr
  Point half = {5};                // implicitValueInitExpr for y
  IntList il = {1, 2, 3};          // cxxStdInitializerListExpr
  Point cl = (Point){9, 8};        // compoundLiteralExpr (C99 in C++)
  const char *fn = __func__;       // predefinedExpr
  void *gnull = __null;            // gnuNullExpr
}

// ---- 3.3 names & members ----------------------------------------------------
struct Counter {
  int count;
  static int total;
  int get() { return count; }             // implicit this
  int both() { return this->count + total; }
};
int Counter::total = 0;
int useCounter(Counter &cnt) { return cnt.count + cnt.get(); }

// ---- 3.4 operators ----------------------------------------------------------
struct Vec2 {
  int x, y;
  Vec2 operator+(const Vec2 &o) const { return {x + o.x, y + o.y}; }
  auto operator<=>(const Vec2 &) const = default;
};
bool nothrow() noexcept;
template <typename... Args> auto sum(Args... args) { return (0 + ... + args); }
int operators(int a, int b, int *arr) {
  int neg = -a;                            // unaryOperator
  int prod = a * b;                        // binaryOperator
  int pick = a ? b : neg;                  // conditionalOperator
  int elvis = a ?: b;                      // binaryConditionalOperator (GNU)
  Vec2 v{1, 2}, w{3, 4};
  Vec2 sumv = v + w;                       // cxxOperatorCallExpr
  bool lt = v < w;                         // cxxRewrittenBinaryOperator
  unsigned long sz = sizeof(a) + alignof(int);
  int elem = arr[1];                       // arraySubscriptExpr
  int par = (a + b) * 2;                   // parenExpr
  bool ne = noexcept(nothrow());           // cxxNoexceptExpr
  return prod + pick + elvis + sumv.x + lt + sz + elem + par + ne;
}

// ---- 3.5 calls & construction ----------------------------------------------
struct Widget {
  Widget();
  Widget(int, int);
  void draw();
};
void withDefault(int x, int y = 0);
int calls() {
  Widget w(1, 2);                          // cxxConstructExpr
  Widget tmp = Widget(3, 4);               // cxxTemporaryObjectExpr
  w.draw();                                // cxxMemberCallExpr
  withDefault(42);                         // cxxDefaultArgExpr
  Widget *heap = new Widget;               // cxxNewExpr
  delete heap;                             // cxxDeleteExpr
  auto lam = [&]() { return bar(); };      // lambdaExpr
  return lam();
}

// ---- 3.6 casts --------------------------------------------------------------
struct Base { virtual ~Base() {} };
struct Derived : Base {};
void casts(Base &base, const int &cref) {
  int truncated = (int)2.2f;                          // cStyleCastExpr
  long functional = long(8);                          // cxxFunctionalCastExpr
  long stat = static_cast<long>(8);                   // cxxStaticCastExpr
  Derived *dyn = dynamic_cast<Derived *>(&base);      // cxxDynamicCastExpr
  char *rein = reinterpret_cast<char *>(&truncated);  // cxxReinterpretCastExpr
  int *cst = const_cast<int *>(&cref);                // cxxConstCastExpr
  long implicit = truncated;                          // implicitCastExpr
}

// ---- 3.7 invisible nodes ----------------------------------------------------
struct Str {
  Str();
  ~Str();
  int size() const;
};
Str make();
void take(Str);
void temporaries() {
  take(make());                    // cxxBindTemporaryExpr + exprWithCleanups
  int n = make().size();           // materializeTemporaryExpr
}
struct Grid { int cells[4]; };
void arrays() {
  int pair[2] = {1, 2};
  auto [first, second] = pair;     // arrayInitLoopExpr + arrayInitIndexExpr
  auto lam = [pair]() { return pair[0]; };
  Grid g1{};
  Grid g2 = g1;                    // implicit copy ctor: arrayInitLoopExpr
}

// ---- 3.8 dependent (template) nodes -----------------------------------------
template <int N> struct Fixed { static const int n = N; };
struct Fixed42 : Fixed<42> {};                       // substNonTypeTemplateParmExpr
template <typename T> T make_one() { T a; return a; }
struct Api {
  template <class T> void call();
  void plain();
};
template <class T> struct Dep : T {
  void run() {
    T t;
    t.go();                        // cxxDependentScopeMemberExpr
    T::value;                      // dependentScopeDeclRefExpr
    make_one<T>();                 // unresolvedLookupExpr
    Api api;
    api.call<T>();                 // unresolvedMemberExpr
    T copy = T(t);                 // cxxUnresolvedConstructExpr
    Dep self(*this);               // parenListExpr
  }
};
template <typename T> concept Dereferencable = requires(T p) { *p; };  // requiresExpr

// ---- 3.9 coroutines ---------------------------------------------------------
struct Task {
  struct promise_type {
    Task get_return_object() { return {}; }
    std::suspend_never initial_suspend() { return {}; }
    std::suspend_never final_suspend() noexcept { return {}; }
    std::suspend_never yield_value(int) { return {}; }
    void return_void() {}
    void unhandled_exception() {}
  };
};
Task coro() {
  co_await std::suspend_never{};
  co_yield 1;
  co_return;
}
template <class A> Task depCoro(A awaitable) {
  co_await awaitable;              // dependentCoawaitExpr
}

// ---- 3.10 exotic C / GNU extensions -----------------------------------------
typedef int int4 __attribute__((ext_vector_type(4)));
typedef float float4 __attribute__((ext_vector_type(4)));
int shared;
int exotic(int a, float fl, int4 iv) {
  int se = ({ int X = 4; X; });                                  // stmtExpr
  void *lp = &&exit_label;                                       // addrLabelExpr
  int chosen = __builtin_choose_expr(1, a, se);                  // chooseExpr
  const char *kind = _Generic(fl, int : "int", float : "float"); // genericSelectionExpr
  float4 fv = __builtin_convertvector(iv, float4);               // convertVectorExpr
  int loaded = __atomic_load_n(&shared, __ATOMIC_SEQ_CST);       // atomicExpr
exit_label:
  return chosen + loaded + (int)fv.x + kind[0];
}
