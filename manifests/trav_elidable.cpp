// Part 9 extra sample: elidable copy constructors exist only before C++17.
// Parse with:  clang-query manifests/trav_elidable.cpp -- -std=c++14
//         and:  clang-query manifests/trav_elidable.cpp -- -std=c++23
struct H {};
H G();
void f() {
  H D = G();
}
