// Feature-flag sample: find every flag string passed to isEnable(), whether
// written inline or through a named constant. No #include.
// Parse with:  clang-query manifests/feature_flags.cpp -- -std=c++23

bool isEnable(const char *Flag);
bool isOther(const char *Flag);

constexpr const char *MyFlag = "MyOption";
const char *const LegacyFlag = "LegacyOption";
const char *RuntimeName();

void viaConstant() {
  if (isEnable(MyFlag)) {}          // FLAG: "MyOption" (constant)
}

void viaLiteral() {
  if (isEnable("MyOption")) {}      // FLAG: "MyOption" (literal)
  if (isEnable(("FastPath"))) {}    // FLAG: "FastPath" (parenthesized literal)
}

void viaConstConstant() {
  if (isEnable(LegacyFlag)) {}      // FLAG: "LegacyOption" (const pointer)
}

void notMatched() {
  if (isEnable(RuntimeName())) {}   // not a literal: no string to report
  if (isOther("MyOption")) {}       // wrong function
}
