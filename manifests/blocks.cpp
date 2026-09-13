// Blocks sample for Part 11. Compile with -std=c++23 -fblocks.

typedef int (^IntOp)(int);
typedef void (^Callback)(int code, const char *msg);

void runOp(IntOp op);
void onDone(Callback cb);

int apply(int seed) {
  int (^twice)(int) = ^(int p) { return p * 2; };
  Callback report = ^(int code, const char *msg) { (void)code; (void)msg; };

  runOp(^(int v) { return v + seed; });
  onDone(report);
  ^{}();

  return twice(seed);
}
