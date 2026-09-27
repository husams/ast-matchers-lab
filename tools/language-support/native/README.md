# Native AST Matcher service

`astmatcher-native` parses matcher expressions with Clang's dynamic matcher
parser and runs them on a source file with `MatchFinder`. It does not launch
`clang-query` or interpret its text output. The [protobuf contract](proto/astmatcher.proto)
is the source of truth for the gRPC service and the CLI's protobuf JSON.

## Build

Install CMake, a C++20 compiler, Clang/LLVM 22 or newer with `clang-cpp`,
protobuf, gRPC C++, `protoc`, and `grpc_cpp_plugin`. On macOS with Homebrew:

```sh
brew install cmake ninja llvm@22 protobuf grpc
cmake -S tools/language-support/native -B tools/language-support/native/build \
  -G Ninja -DCMAKE_PREFIX_PATH="$(brew --prefix llvm@22);$(brew --prefix protobuf);$(brew --prefix grpc)"
cmake --build tools/language-support/native/build
ctest --test-dir tools/language-support/native/build --output-on-failure
```

On Linux, install the equivalent development packages and point
`CMAKE_PREFIX_PATH` at nonstandard LLVM/gRPC installations if needed.

## Run

Use a short absolute socket path. macOS limits Unix socket paths to 103 bytes.
The endpoint URI used by gRPC is `unix:///absolute/path.sock`.

```sh
tools/language-support/native/build/astmatcher-native serve --socket /tmp/astmatcher.sock
```

An editor can pass `--parent-pid PID` after the socket path; the service shuts
down and removes its socket if that parent exits, including after SIGTERM.

In another terminal, check readiness and send a protobuf JSON `RunRequest` to
the CLI bridge:

```sh
tools/language-support/native/build/astmatcher-native ping --socket /tmp/astmatcher.sock
```

Ping returns `compilerPath`, the absolute Clang executable from the LLVM
installation linked into this service. Clients should use that compiler for
dependency scans and cache keys.

```sh
cat <<'JSON' | tools/language-support/native/build/astmatcher-native query --socket /tmp/astmatcher.sock
{
  "sourcePath": "/absolute/path/to/sample.cpp",
  "workingDirectory": "/absolute/path/to",
  "flags": ["-std=c++23"],
  "traversal": "AsIs",
  "maxMatches": 1000,
  "commands": [
    {"kind": "LET", "name": "f", "expression": "functionDecl(hasName(\"main\"))"},
    {"kind": "MATCH", "expression": "f"}
  ]
}
JSON
```

`query` accepts `--timeout-ms N` after the socket path, with `N` from 1 to
3600000. The default is 120000 ms. A gRPC deadline returns exit status 124
and writes `Matcher server request timed out after N ms` to stderr.
When `flags` is empty, Clang chooses the language and standard from the source
file extension.

`RunReply.queries` follows the input `MATCH` commands. `count` is the full
number of matches; `matches` is limited to `maxMatches` across the request,
and `truncated` reports when that limit was exceeded. Zero `maxMatches` uses
the default of 1000; values above 10000 are capped at 10000. Bindings carry
opaque node identities that remain stable across matches in one request.
Ranges use zero-based UTF-16 positions with an exclusive end. Clang source
diagnostics appear in `stderr`; matcher command diagnostics appear in
`diagnostics` with zero-based command indexes and expression positions.
Compiler diagnostic text is capped at 64 KB with a truncation marker.

The server serializes `Run` requests because Clang tooling does not promise
concurrent invocations within one process. The socket has local filesystem
permissions (`0600`); run one server per editor workspace or user session.
