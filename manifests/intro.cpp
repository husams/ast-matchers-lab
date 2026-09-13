// intro.cpp — sample for Part 1. No #include; parses with -std=c++23.

int add(int a, int b) { return a + b; }
int twice(int x) { return add(x, x); }
int total() { return 1 + 2 + 3; }

struct Point {
  int x;
  int y;
  int sum() const { return x + y; }
};

// --- traversal-mode cases, taken from the reference ---------------------

struct B {
  B(int);
};
B func1() { return 42; }

struct Foo {};
Foo copies() {
  Foo f;
  Foo g = f;
  return g;
}

struct Cont {
  int *begin();
  int *end();
};
int iterate() {
  Cont c;
  int n = 0;
  for (auto i : c)
    n += i;
  return n;
}

template <typename T>
struct TemplStruct {
  TemplStruct() {}
  ~TemplStruct() {}

private:
  T m_t;
};
void instantiate() {
  TemplStruct<int> ti;
  TemplStruct<double> td;
}
