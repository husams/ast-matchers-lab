cmake_minimum_required(VERSION 3.20)
project(astmatcher_native LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)
if(LLVM_VERSION_MAJOR LESS 21)
  message(FATAL_ERROR "Clang/LLVM 21 or newer is required")
endif()
find_package(Protobuf QUIET CONFIG)
if(NOT Protobuf_FOUND)
  find_package(Protobuf REQUIRED)
endif()
find_package(gRPC REQUIRED CONFIG)

set(PROTO_FILE "${CMAKE_CURRENT_SOURCE_DIR}/proto/astmatcher.proto")
set(GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${GENERATED_DIR}")
if(NOT IS_ABSOLUTE "${LLVM_TOOLS_BINARY_DIR}")
  message(FATAL_ERROR "LLVM_TOOLS_BINARY_DIR must be an absolute path")
endif()
set(ASTMATCHER_COMPILER_PATH "${LLVM_TOOLS_BINARY_DIR}/clang")
if(NOT EXISTS "${ASTMATCHER_COMPILER_PATH}")
  message(FATAL_ERROR "Matching Clang compiler not found: ${ASTMATCHER_COMPILER_PATH}")
endif()
execute_process(
  COMMAND "${ASTMATCHER_COMPILER_PATH}" -print-resource-dir
  OUTPUT_VARIABLE ASTMATCHER_RESOURCE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE RESOURCE_DIR_STATUS
)
if(NOT RESOURCE_DIR_STATUS EQUAL 0 OR
   NOT EXISTS "${ASTMATCHER_RESOURCE_DIR}/include/stddef.h")
  message(FATAL_ERROR
    "Matching Clang resource headers not found for ${ASTMATCHER_COMPILER_PATH}: ${ASTMATCHER_RESOURCE_DIR}")
endif()
file(REAL_PATH "${ASTMATCHER_RESOURCE_DIR}" ASTMATCHER_RESOURCE_DIR)
configure_file(
  "${CMAKE_CURRENT_SOURCE_DIR}/include/compiler_config.h.in"
  "${GENERATED_DIR}/compiler_config.h"
  @ONLY
)

if(TARGET protobuf::protoc)
  set(PROTOC "$<TARGET_FILE:protobuf::protoc>")
else()
  find_program(PROTOC protoc REQUIRED)
endif()
if(TARGET gRPC::grpc_cpp_plugin)
  set(GRPC_CPP_PLUGIN "$<TARGET_FILE:gRPC::grpc_cpp_plugin>")
else()
  find_program(GRPC_CPP_PLUGIN grpc_cpp_plugin REQUIRED)
endif()

add_custom_command(
  OUTPUT
    "${GENERATED_DIR}/astmatcher.pb.cc"
    "${GENERATED_DIR}/astmatcher.pb.h"
    "${GENERATED_DIR}/astmatcher.grpc.pb.cc"
    "${GENERATED_DIR}/astmatcher.grpc.pb.h"
  COMMAND "${PROTOC}"
    "--proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto"
    "--cpp_out=${GENERATED_DIR}"
    "--grpc_out=${GENERATED_DIR}"
    "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN}"
    "${PROTO_FILE}"
  DEPENDS "${PROTO_FILE}"
  VERBATIM
)

add_executable(astmatcher-native
  src/main.cpp
  src/matcher_engine.cpp
  "${GENERATED_DIR}/astmatcher.pb.cc"
  "${GENERATED_DIR}/astmatcher.grpc.pb.cc"
)
target_include_directories(astmatcher-native PRIVATE
  include
  "${GENERATED_DIR}"
  "${LLVM_INCLUDE_DIRS}"
  "${CLANG_INCLUDE_DIRS}"
)
target_link_libraries(astmatcher-native PRIVATE
  clang-cpp
  LLVM
  protobuf::libprotobuf
  gRPC::grpc++
)

enable_testing()
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
  add_test(NAME astmatcher_native_smoke
    COMMAND "${Python3_EXECUTABLE}"
      "${CMAKE_CURRENT_SOURCE_DIR}/tests/smoke.py"
      "$<TARGET_FILE:astmatcher-native>"
      "${CMAKE_CURRENT_SOURCE_DIR}/../../../manifests/intro.cpp"
  )
endif()
