/* designators.c — tiny C sample for designatorCountIs (Part 6).
   Nested and array designators are C-only; parses with -std=c17. */

struct point {
  double x;
  double y;
};

struct point ptarray[10] = {[2].y = 1.0, [0].x = 1.0};
struct point ptarray2[10] = {[2].y = 1.0, [2].x = 0.0, [0].x = 1.0};
struct point single = {.x = 1.0, .y = 2.0};
