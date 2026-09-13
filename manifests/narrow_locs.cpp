// narrow_locs.cpp — Part 7.4 sample: source locations and macros
// Run: $LLVM/bin/clang-query manifests/narrow_locs.cpp -- -std=c++23 -isystem manifests/include
#include <sys.h>
#include "include/helpers.h"

#define SQUARE(x) ((x) * (x))
#define DECLARE_COUNTER(name) int name = 0
#define LOG(msg) log_line(msg)

class Local { public: int id; };
DECLARE_COUNTER(hits);

int twice(int n) { return SQUARE(n); }

void run() {
  LOG("start");
  hits = SQUARE(hits) + 1;
  helper_count = sys_clamp(hits);
}
