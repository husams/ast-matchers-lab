// Part 12 sample: a "legacy" module with deliberate smells, no #include.
// Parse with:  clang-query manifests/capstone.cpp -- -std=c++23
// Each smell is tagged  // SMELL:<check>  so you can grep what a query should find.

// The smells below are exactly what the compiler's default warnings catch;
// silence them so clang-query output is the only thing you read.
#pragma clang diagnostic ignored "-Wparentheses"
#pragma clang diagnostic ignored "-Wself-assign"
#pragma clang diagnostic ignored "-Wself-assign-field"
#pragma clang diagnostic ignored "-Wswitch"
#pragma clang diagnostic ignored "-Winconsistent-missing-override"

#define NULL 0
#define CHECK(cond) if (!(cond)) fail_fast()
#define MAX_ITEMS 64

void fail_fast();
void log_line(const char* msg);

// ---- hand-written "std-like" container ----------------------------------
struct Vec {
  int* data;
  unsigned len;
  Vec() : data(NULL), len(0) {}                          // SMELL:nullptr
  Vec(const Vec& other);
  Vec& operator=(const Vec& other);
  ~Vec();
  unsigned size() const { return len; }
  bool empty() const { return len == 0; }
  void push(int v);
  int at(unsigned i) const { return data[i]; }
};

struct Counter {                       // has size() but no empty(): not a container smell
  unsigned n;
  unsigned size() const { return n; }
};

enum Color { Red, Green, Blue };
enum class Mode { Fast, Safe };

// ---- 12.1 null pointer constants -----------------------------------------
int* find_slot(Vec& v, int key) {
  for (unsigned i = 0; i < v.size(); ++i)
    if (v.at(i) == key) return &v.data[i];
  return 0;                                              // SMELL:nullptr
}

void use_slots(Vec& v) {
  int* a = NULL;                                         // SMELL:nullptr
  int* b = nullptr;                                      // fine
  const char* label = 0;                                 // SMELL:nullptr
  if (a == 0) log_line("a is null");                     // SMELL:nullptr
  if (b != nullptr) log_line("b set");                   // fine
  a = find_slot(v, 3);
  if (label == NULL) label = "none";                     // SMELL:nullptr
  log_line(label);
}

// ---- 12.2 / 12.6 class hierarchies ---------------------------------------
class Widget {
public:
  virtual ~Widget() {}
  virtual void draw() const {}
  virtual void resize(int w, int h) {}
  virtual int id() const { return 0; }
  virtual void hide() {}
};

class Button : public Widget {
public:
  ~Button() {}                                           // SMELL:override
  void draw() const override {}                          // fine
  void resize(int w, int h) {}                           // SMELL:override
  int id() const final { return 1; }                     // fine: final implies override
  void hide() override final {}                          // fine
};

class Label : public Button {
public:
  void draw() const {}                                   // SMELL:override
  void resize(int w, int h) override {}                  // fine
};

struct Shape {                         // SMELL:non-virtual-dtor (implicit destructor)
  virtual double area() const { return 0.0; }
  struct Inner {                       // nested: has its own virtual dtor, must not rescue Shape
    virtual ~Inner() {}
  };
};

struct Polygon : Shape {               // SMELL:non-virtual-dtor (declared, not virtual)
  ~Polygon() {}
  double area() const override { return 1.0; }
};

struct Plain {                         // no virtual methods at all: not a smell
  ~Plain() {}
  int value() const { return 3; }
};

// ---- 12.3 size() == 0 comparisons ----------------------------------------
void report(const Vec& v, const Counter& c) {
  if (v.size() == 0) log_line("empty");                  // SMELL:size-empty
  if (0 == v.size()) log_line("empty again");            // SMELL:size-empty
  if (v.size() != 0) log_line("has items");              // SMELL:size-empty
  if (v.size() > 0) log_line("has items");               // SMELL:size-empty
  if (v.empty()) log_line("ok, idiomatic");              // fine
  if (c.size() == 0) log_line("counter empty");          // fine: Counter has no empty()
  if (v.size() == MAX_ITEMS) log_line("full");           // fine: not a zero comparison
}

// ---- 12.4 assignment in condition & self-assignment ----------------------
int next_token();

struct Cursor {
  int pos;
  int limit;
  Cursor(int pos, int limit) : pos(pos), limit(limit) {}
  void reset(int pos) { pos = pos; }                     // SMELL:self-assign (param shadows field)
  void clamp() {
    if (pos > limit) pos = limit;                        // fine: assignment in the body
    limit = limit;                                       // SMELL:self-assign
  }
};

void scan(Cursor& c) {
  int tok;
  if (tok = next_token()) log_line("got token");         // SMELL:assign-in-if
  if ((tok = next_token()) != 0) log_line("explicit");   // fine: comparison wraps it
  while (tok = next_token()) c.pos++;                    // not an if: out of scope for 12.4
  if (tok == 0) log_line("done");                        // fine
  c.pos = c.pos;                                         // SMELL:self-assign (member)
}

// ---- 12.5 heavy parameters passed by value -------------------------------
unsigned total(Vec v) {                                  // SMELL:value-param (never modified)
  unsigned sum = 0;
  for (unsigned i = 0; i < v.size(); ++i) sum += v.at(i);
  return sum;
}

void grow(Vec v) {                                       // fine: v is modified
  v.push(1);
}

void replace(Vec v, const Vec& src) {                    // fine: v is assigned to
  v = src;
}

void describe(Counter c) {                               // fine: Counter has no user-written copy ctor
  if (c.size() == 0) log_line("zero");
}

void show(const Vec& v) {                                // fine: already a const reference
  log_line(v.empty() ? "empty" : "items");
}

// ---- 12.7 switches over enums --------------------------------------------
const char* color_name(Color c) {
  switch (c) {                                           // SMELL:missing-default
    case Red:   return "red";
    case Green: return "green";
  }
  return "?";
}

const char* mode_name(Mode m) {
  switch (m) {                                           // fine: has default
    case Mode::Fast: return "fast";
    default:         return "safe";
  }
}

int decode(int raw, Color fallback) {
  switch (raw) {                                         // fine for 12.7: not an enum
    case 1: return 10;
    case 2: return 20;
  }
  switch (fallback) {                                    // SMELL:missing-default (nested default must not count)
    case Blue:
      switch (raw) { default: return 30; }
      break;
    case Red:
      break;
  }
  return 0;
}

// ---- 12.8 macros ---------------------------------------------------------
void validate(const Vec& v) {
  CHECK(v.size() < MAX_ITEMS);                           // if from the CHECK macro
  CHECK(v.data != NULL);                                 // if from CHECK, NULL inside it
  if (v.len > MAX_ITEMS) fail_fast();                    // hand-written if
}
