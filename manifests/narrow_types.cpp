// narrow_types.cpp — Part 7 sample: QualType predicates, sizes, bound-node equality
// Run: $LLVM/bin/clang-query manifests/narrow_types.cpp -- -std=c++23

// ---- 7.1 QualType predicates: seen through parameters -----------------
void takes_int(int);
void takes_ulong(unsigned long);
void takes_double(double);
void takes_char(char);
void takes_wchar(wchar_t);

void by_value(int);
void const_param(int const);
void const_param2(const int);
void ptr_to_const(const int*);

// ---- 7.1 QualType predicates: seen through variables -------------------
typedef const int const_int;
const_int ci = 1;
int *const jp = nullptr;
int *volatile kp = nullptr;
volatile int vol = 0;
volatile int *vp = nullptr;
int m = 0;
int *ip = nullptr;
int plain = 0;

class Y { public: void x(); };
void z() { Y obj; Y *y = &obj; y->x(); }
void Y::x() {}

// ---- 7.1 QualType predicates: seen through return types ----------------
bool flag();
void nothing();
float ratio();
double avg();
long double precise();

// ---- 7.2 sizes: arrays and string literals -----------------------------
int a[42];
int b[2 * 21];
int c[41], d[43];
const char *s = "abcd";
const wchar_t *ws = L"abcd";
const char *w = "a";

// ---- 7.5 bound-node equality -------------------------------------------
struct Pair { int first; int second; };
struct Mixed { int count; double ratio; };
struct Qual { int raw; const int fixed = 0; };

int self = 0;
void assign_self() { self = self; m = self; }

void use_locals() {
  int u = 1;
  int v = u + 1;
  m = v;
}

int pick(int lhs, int rhs) { return lhs == rhs ? lhs : rhs; }
