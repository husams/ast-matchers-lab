// Fixed-point literals are a C (Embedded C TR 18037) extension: needs -ffixed-point.
// Compile check:  clang -ffixed-point -fsyntax-only manifests/stmts_fixedpoint.c
short _Accum sa = 2;      /* implicit conversion, not a literal */
_Accum a = 12.5;          /* float literal, not a fixed-point literal */
_Accum b = 1.25hk;        /* fixedPointLiteral */
_Fract c = 0.25hr;        /* fixedPointLiteral */
_Accum g = 1.45uhk;       /* fixedPointLiteral */
_Accum e = 1.575e1k;      /* fixedPointLiteral */
