// sys.h — pretend system header; reached through -isystem manifests/include
#pragma once
class SysBuffer { public: int size; };
void log_line(const char *msg);
inline int sys_clamp(int v) { return v < 0 ? 0 : v; }
