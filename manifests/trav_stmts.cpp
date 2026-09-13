// Part 9 sample: statements & expressions for the traversal matchers.
// Parse with:  clang-query manifests/trav_stmts.cpp -- -std=c++23
// No #include — every std:: name used below is a hand-written stub.

// ---- std:: stubs ---------------------------------------------------------
namespace std {
struct strong_ordering {
  int value;
  static const strong_ordering less;
  static const strong_ordering equal;
  static const strong_ordering greater;
  friend constexpr bool operator==(strong_ordering a, int) noexcept { return a.value == 0; }
  friend constexpr bool operator<(strong_ordering a, int) noexcept { return a.value < 0; }
  friend constexpr bool operator>(strong_ordering a, int) noexcept { return a.value > 0; }
  friend constexpr bool operator<=(strong_ordering a, int) noexcept { return a.value <= 0; }
  friend constexpr bool operator>=(strong_ordering a, int) noexcept { return a.value >= 0; }
};
inline constexpr strong_ordering strong_ordering::less{-1};
inline constexpr strong_ordering strong_ordering::equal{0};
inline constexpr strong_ordering strong_ordering::greater{1};

template <typename Ret, typename... Args>
struct coroutine_traits { using promise_type = typename Ret::promise_type; };
template <typename Promise = void>
struct coroutine_handle {
  static coroutine_handle from_address(void*) noexcept { return {}; }
};
}  // namespace std

// ---- 9.1 calls -----------------------------------------------------------
void log(int level, const char* msg);
void log(int level);
void (*log_ptr)(int) = log;
int width;

struct Counter {
  int n;
  void bump();
  void bump(int by);
  int get() const;
};
struct Sub : Counter { void extra(); };
Counter make();

struct Widget {
  Widget(int w, int h);
  int w, h;
};

void calls(Counter c, Sub s, Counter* p) {
  log(width, "w");
  log(3);
  log_ptr(width);
  c.bump();
  c.bump(width);
  s.bump();
  s.extra();
  p->bump();
  (make()).bump();
  Widget box(3, 4);
}

struct Stack { void push(int); void push(double); };
template <typename T> void over(T);
template <typename T> void over(T, int);
template <typename T> void other(T);

template <typename T>
T inspect(T t, Stack& s) {
  over(t);
  other(t);
  s.push(t);
  t.size();
  return T(t);
}

// ---- 9.2 operators -------------------------------------------------------
struct Vec {
  int x, y;
  Vec operator+(Vec o) const;
  Vec operator-() const;
  bool operator==(const Vec&) const = default;
  std::strong_ordering operator<=>(const Vec&) const = default;
};
Vec operator*(Vec a, int k);

template <typename... Ts> auto sum(Ts... ts) { return (0 + ... + ts); }
template <typename... Ts> auto product(Ts... ts) { return (ts * ... * 1); }
template <typename... Ts> auto all(Ts... ts) { return (... && ts); }

int grid[8];

void operators(Vec a, Vec b, int i) {
  int t = i * 2 + 1;
  bool both = (i > 0) || (i < 8);
  Vec c = a + b;
  Vec d = -a;
  Vec e = a * 3;
  bool ne = a != b;
  bool lt = a < b;
  grid[i] = 42;
  int u = -i;
  bool nb = !both;
}

// ---- 9.3 control flow ----------------------------------------------------
int probe();
struct Node { int val; Node* next; };
Node* head();
struct Range { int* begin(); int* end(); };
Range values();

int control(int n) {
  if (n > 0) { n = 1; } else { n = 2; }
  if (int k = probe(); k > 3) { n += k; }
  if (Node* nd = head()) { n = nd->val; }
  for (int i = 0; i < n; ++i) { n -= 1; }
  for (; Node* nd = head();) { n = nd->val; }
  while (n > 100) { --n; }
  while (Node* nd = head()) { n = nd->val; }
  do { n++; } while (n < 10);
  switch (n) {
    case 1: n = 10; break;
    case 2 ... 4: n = 20; break;
    default: break;
  }
  switch (int m = probe(); m) { case 1: break; }
  switch (int m = probe()) { default: break; }
  for (int v : values()) { n += v; }
  for (auto r = values(); int v : r) { n += v; }
  int k = n ? n : 1;
  int g = n ?: 7;
  int se = ({ int tmp = n * 2; tmp + 1; });
  { {} n = k + g + se; }
  return n + k;
}

struct Ready {
  bool await_ready() const noexcept { return true; }
  template <typename H> void await_suspend(H) const noexcept {}
  void await_resume() const noexcept {}
};
struct Task {
  struct promise_type {
    Task get_return_object() { return {}; }
    Ready initial_suspend() noexcept { return {}; }
    Ready final_suspend() noexcept { return {}; }
    void return_void() {}
    void unhandled_exception() {}
  };
};
Task ticker() { co_return; }

// ---- 9.4 declarations inside statements ----------------------------------
struct Pair { int first, second; };

struct Holder {
  int m;
  Pair pr;
  int self(Holder h) {
    int a = h.m;
    return a + m + pr.first;
  }
};

void decls() {
  int a, b = 0;
  int c;
  int d = 2, e;
  Pair p{1, 2};
  c = p.first;
  e = p.second;
  a = b + c + d + e;
}

int pick(int v) {
  auto positive = [](int q) { return q > 0; };
  if (positive(v)) return v;
  return 0;
}

// ---- 9.5 the ignoring* family --------------------------------------------
struct Cell {};
Cell make_cell();

void ignoring() {
  int arr[5];
  int a = 0;
  char b = (0);
  const int c = a;
  int* d = (arr);
  long e = ((long)0l);
  void* f = reinterpret_cast<char*>(0);
  char g = char(0);
  Cell h = Cell();
  Cell i;
  Cell j = i;
  Cell k = make_cell();
}

// ---- 9.6 casts -----------------------------------------------------------
struct Url { Url(const char* s); };
Url home = "https://example.test";
const char* label = ("my-string");

// ---- 9.7 new/delete & init lists -----------------------------------------
struct Thing { int id; Thing(); };
void* operator new(__SIZE_TYPE__ size, void* where) noexcept;
void* operator new(__SIZE_TYPE__ size, void* where, int align) noexcept;
char storage[64];

void allocate() {
  Thing* one = new Thing;
  Thing* many = new Thing[10];
  Thing* placed = new (storage) Thing();
  Thing* aligned = new (storage, 16) Thing();
  delete one;
  delete[] many;
  int nums[3] = {1, 2, 3};
  Pair named = {.first = 4, .second = 5};
  int box[2][2] = {1, 2, 3, 4};
}

// ---- 9.8 lambdas ---------------------------------------------------------
void lambdas() {
  int x = 1, y = 2;
  float z = 3;
  auto by_val = [x]() { return x; };
  auto init_cap = [x = 1]() { return x; };
  auto all_copy = [=]() { return x + y + z; };
  auto by_ref = [&y]() { y++; };
  by_ref();
}

// ---- 9.9 sizeof / alignof ------------------------------------------------
void sizes() {
  int a;
  float b;
  int s = sizeof(a) + sizeof(b) + alignof(int);
  unsigned long t = sizeof(Thing) + alignof(Thing);
}
