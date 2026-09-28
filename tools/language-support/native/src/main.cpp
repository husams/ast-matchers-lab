#include <atomic>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <iterator>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <future>
#include <string>
#include <string_view>
#include <thread>

#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include "astmatcher.grpc.pb.h"
#include "compiler_config.h"
#include "google/protobuf/util/json_util.h"
#include "grpcpp/grpcpp.h"
#include "matcher_engine.h"
#include "clang/ASTMatchers/Dynamic/Registry.h"

namespace {

constexpr int kMaximumMessageBytes = 64 * 1024 * 1024;
constexpr uint32_t kDefaultQueryTimeoutMs = 120000;
constexpr uint32_t kMaximumQueryTimeoutMs = 3600000;

template <typename Options> void include_default_json_fields(Options &options) {
  if constexpr (requires(Options &value) {
                  value.always_print_fields_with_no_presence;
                }) {
    options.always_print_fields_with_no_presence = true;
  } else {
    options.always_print_primitive_fields = true;
  }
}

class MatcherService final
    : public astmatcher::native::v1::MatcherService::Service {
public:
  grpc::Status Ping(grpc::ServerContext *,
                    const astmatcher::native::v1::PingRequest *,
                    astmatcher::native::v1::PingReply *reply) override {
    reply->set_version("1");
    reply->set_compiler_path(ASTMATCHER_COMPILER_PATH);
    return grpc::Status::OK;
  }

  grpc::Status Run(grpc::ServerContext *,
                   const astmatcher::native::v1::RunRequest *request,
                   astmatcher::native::v1::RunReply *reply) override {
    // Clang's dynamic registry and source manager are not documented as safe
    // for concurrent tooling invocations in one process.
    const std::lock_guard<std::mutex> guard(mutex_);
    *reply = astmatcher::native::run_match_request(*request);
    return grpc::Status::OK;
  }

  grpc::Status InspectRecord(
      grpc::ServerContext *,
      const astmatcher::native::v1::InspectRecordRequest *request,
      astmatcher::native::v1::InspectRecordReply *reply) override {
    const std::lock_guard<std::mutex> guard(mutex_);
    *reply = astmatcher::native::inspect_record_request(*request);
    return grpc::Status::OK;
  }

  grpc::Status RunWithProgress(
      grpc::ServerContext *context,
      const astmatcher::native::v1::RunRequest *request,
      grpc::ServerWriter<astmatcher::native::v1::RunProgress> *writer) override {
    using namespace std::chrono_literals;
    using astmatcher::native::v1::RunProgress;
    const std::lock_guard<std::mutex> guard(mutex_);
    const auto started = std::chrono::steady_clock::now();
    auto request_copy = *request;
    std::promise<astmatcher::native::v1::RunReply> promise;
    auto future = promise.get_future();
    RunProgress initial;
    initial.set_source_path(request->source_path());
    initial.set_elapsed_ms(0);
    bool connected = writer->Write(initial);
    std::thread worker([request = std::move(request_copy),
                        promise = std::move(promise)]() mutable {
      promise.set_value(astmatcher::native::run_match_request(request));
    });
    auto next_report = started;
    do {
      if (future.wait_for(250ms) == std::future_status::ready) {
        break;
      }
      const auto now = std::chrono::steady_clock::now();
      if (connected && now >= next_report) {
        RunProgress progress;
        progress.set_source_path(request->source_path());
        progress.set_elapsed_ms(std::chrono::duration_cast<std::chrono::milliseconds>(
                                    now - started)
                                    .count());
        connected = writer->Write(progress);
        next_report = now + 1s;
      }
    } while (true);
    auto reply = future.get();
    worker.join();
    if (!connected || context->IsCancelled()) {
      return grpc::Status(grpc::StatusCode::CANCELLED, "progress client disconnected");
    }
    RunProgress complete;
    complete.set_source_path(request->source_path());
    complete.set_elapsed_ms(std::chrono::duration_cast<std::chrono::milliseconds>(
                                std::chrono::steady_clock::now() - started)
                                .count());
    complete.set_complete(true);
    *complete.mutable_reply() = std::move(reply);
    if (!writer->Write(complete)) {
      return grpc::Status(grpc::StatusCode::CANCELLED, "progress client disconnected");
    }
    return grpc::Status::OK;
  }

private:
  std::mutex mutex_;
};

bool valid_socket_path(const std::string &path) {
  if (path.empty() || path.front() != '/') {
    std::cerr << "--socket requires an absolute path\n";
    return false;
  }
  if (path.size() >= sizeof(sockaddr_un::sun_path)) {
    std::cerr << "Socket path is too long for this operating system\n";
    return false;
  }
  return true;
}

std::string grpc_address(const std::string &socket_path) {
  return "unix://" + socket_path;
}

bool clear_stale_socket(const std::string &path) {
  struct stat information{};
  if (lstat(path.c_str(), &information) != 0) {
    return errno == ENOENT;
  }
  if (!S_ISSOCK(information.st_mode)) {
    std::cerr << "Socket path exists and is not a socket: " << path << '\n';
    return false;
  }
  const int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
  if (descriptor < 0) {
    std::cerr << "Cannot inspect existing socket: " << std::strerror(errno)
              << '\n';
    return false;
  }
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  std::strncpy(address.sun_path, path.c_str(), sizeof(address.sun_path) - 1);
  const int result =
      connect(descriptor, reinterpret_cast<const sockaddr *>(&address),
              sizeof(address));
  const int connect_error = errno;
  close(descriptor);
  if (result == 0) {
    std::cerr << "A server is already listening at " << path << '\n';
    return false;
  }
  if (connect_error != ECONNREFUSED && connect_error != ENOENT) {
    std::cerr << "Cannot inspect existing socket: "
              << std::strerror(connect_error) << '\n';
    return false;
  }
  if (unlink(path.c_str()) != 0) {
    std::cerr << "Cannot remove stale socket: " << std::strerror(errno) << '\n';
    return false;
  }
  return true;
}

int serve(const std::string &socket_path, std::optional<pid_t> parent_pid) {
  if (!clear_stale_socket(socket_path)) {
    return 1;
  }
  MatcherService service;
  grpc::ServerBuilder builder;
  builder.SetMaxReceiveMessageSize(kMaximumMessageBytes);
  builder.SetMaxSendMessageSize(kMaximumMessageBytes);
  int selected_port = 0;
  builder.AddListeningPort(grpc_address(socket_path),
                           grpc::InsecureServerCredentials(), &selected_port);
  builder.RegisterService(&service);
  const mode_t previous_umask = umask(0077);
  std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  umask(previous_umask);
  if (!server) {
    std::cerr << "Could not start matcher server at " << socket_path << '\n';
    return 1;
  }
  if (chmod(socket_path.c_str(), 0600) != 0) {
    std::cerr << "Could not protect matcher socket: " << std::strerror(errno)
              << '\n';
    server->Shutdown();
    server->Wait();
    unlink(socket_path.c_str());
    return 1;
  }
  std::cerr << "Matcher server listening at " << socket_path << '\n';
  auto stopping = std::make_shared<std::atomic<bool>>(false);
  std::thread parent_watcher;
  if (parent_pid) {
    parent_watcher = std::thread([&, stopping] {
      while (!stopping->load()) {
        if (getppid() != *parent_pid) {
          // ClangTool may keep a synchronous Run active after gRPC's shutdown
          // deadline. The detached guard guarantees this orphan exits anyway.
          std::thread([stopping, socket_path] {
            std::this_thread::sleep_for(std::chrono::seconds(3));
            if (!stopping->load()) {
              unlink(socket_path.c_str());
              std::_Exit(0);
            }
          }).detach();
          server->Shutdown(std::chrono::system_clock::now() +
                           std::chrono::seconds(2));
          return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
    });
  }
  server->Wait();
  stopping->store(true);
  if (parent_watcher.joinable()) {
    parent_watcher.join();
  }
  unlink(socket_path.c_str());
  return 0;
}

int query(const std::string &socket_path, uint32_t timeout_ms, bool progress_enabled) {
  const std::string input(std::istreambuf_iterator<char>(std::cin), {});
  astmatcher::native::v1::RunRequest request;
  const auto parse_status =
      google::protobuf::util::JsonStringToMessage(input, &request);
  if (!parse_status.ok()) {
    std::cerr << "Invalid RunRequest JSON: " << parse_status.message() << '\n';
    return 2;
  }
  grpc::ChannelArguments arguments;
  arguments.SetMaxReceiveMessageSize(kMaximumMessageBytes);
  auto channel = grpc::CreateCustomChannel(
      grpc_address(socket_path), grpc::InsecureChannelCredentials(), arguments);
  auto stub = astmatcher::native::v1::MatcherService::NewStub(channel);
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() +
                       std::chrono::milliseconds(timeout_ms));
  astmatcher::native::v1::RunReply reply;
  grpc::Status rpc_status;
  if (progress_enabled) {
    auto reader = stub->RunWithProgress(&context, request);
    astmatcher::native::v1::RunProgress event;
    while (reader->Read(&event)) {
      if (event.complete()) {
        reply = event.reply();
        continue;
      }
      std::string progress_json;
      google::protobuf::util::JsonPrintOptions progress_options;
      include_default_json_fields(progress_options);
      const auto progress_status = google::protobuf::util::MessageToJsonString(
          event, &progress_json, progress_options);
      if (!progress_status.ok()) {
        context.TryCancel();
        break;
      }
      std::cout << "{\"progress\":" << progress_json << "}\n" << std::flush;
    }
    rpc_status = reader->Finish();
  } else {
    rpc_status = stub->Run(&context, request, &reply);
  }
  if (!rpc_status.ok()) {
    if (rpc_status.error_code() == grpc::StatusCode::DEADLINE_EXCEEDED) {
      std::cerr << "Matcher server request timed out after " << timeout_ms
                << " ms\n";
      return 124;
    }
    std::cerr << "Matcher server request failed: " << rpc_status.error_message()
              << '\n';
    return 1;
  }
  google::protobuf::util::JsonPrintOptions options;
  include_default_json_fields(options);
  std::string output;
  const auto json_status =
      google::protobuf::util::MessageToJsonString(reply, &output, options);
  if (!json_status.ok()) {
    std::cerr << "Cannot serialize RunReply JSON: " << json_status.message()
              << '\n';
    return 1;
  }
  std::cout << output << '\n';
  return 0;
}

int inspect(const std::string &socket_path, uint32_t timeout_ms) {
  const std::string input(std::istreambuf_iterator<char>(std::cin), {});
  astmatcher::native::v1::InspectRecordRequest request;
  const auto parse_status =
      google::protobuf::util::JsonStringToMessage(input, &request);
  if (!parse_status.ok()) {
    std::cerr << "Invalid InspectRecordRequest JSON: " << parse_status.message() << '\n';
    return 2;
  }
  grpc::ChannelArguments arguments;
  arguments.SetMaxReceiveMessageSize(kMaximumMessageBytes);
  auto channel = grpc::CreateCustomChannel(
      grpc_address(socket_path), grpc::InsecureChannelCredentials(), arguments);
  auto stub = astmatcher::native::v1::MatcherService::NewStub(channel);
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() +
                       std::chrono::milliseconds(timeout_ms));
  astmatcher::native::v1::InspectRecordReply reply;
  const auto rpc_status = stub->InspectRecord(&context, request, &reply);
  if (!rpc_status.ok()) {
    std::cerr << "Matcher server record inspection failed: "
              << rpc_status.error_message() << '\n';
    return rpc_status.error_code() == grpc::StatusCode::DEADLINE_EXCEEDED ? 124 : 1;
  }
  google::protobuf::util::JsonPrintOptions options;
  include_default_json_fields(options);
  std::string output;
  const auto json_status =
      google::protobuf::util::MessageToJsonString(reply, &output, options);
  if (!json_status.ok()) {
    std::cerr << "Cannot serialize InspectRecordReply JSON: "
              << json_status.message() << '\n';
    return 1;
  }
  std::cout << output << '\n';
  return 0;
}

int ping(const std::string &socket_path) {
  auto channel = grpc::CreateChannel(grpc_address(socket_path),
                                     grpc::InsecureChannelCredentials());
  auto stub = astmatcher::native::v1::MatcherService::NewStub(channel);
  grpc::ClientContext context;
  context.set_deadline(std::chrono::system_clock::now() +
                       std::chrono::seconds(2));
  astmatcher::native::v1::PingRequest request;
  astmatcher::native::v1::PingReply reply;
  const grpc::Status rpc_status = stub->Ping(&context, request, &reply);
  if (!rpc_status.ok()) {
    std::cerr << "Matcher server ping failed: " << rpc_status.error_message()
              << '\n';
    return 1;
  }
  std::string output;
  const auto json_status =
      google::protobuf::util::MessageToJsonString(reply, &output);
  if (!json_status.ok()) {
    std::cerr << "Cannot serialize PingReply JSON: " << json_status.message()
              << '\n';
    return 1;
  }
  std::cout << output << '\n';
  return 0;
}

int capabilities() {
  std::string name;
  while (std::getline(std::cin, name)) {
    if (clang::ast_matchers::dynamic::Registry::lookupMatcherCtor(name)) {
      std::cout << name << '\n';
    }
  }
  return std::cin.bad() ? 1 : 0;
}

} // namespace

int main(int argc, char **argv) {
  const auto usage = [] {
    std::cerr << "Usage: astmatcher-native serve --socket /absolute/path.sock "
                 "[--parent-pid PID]\n"
                 "       astmatcher-native ping --socket /absolute/path.sock\n"
                 "       astmatcher-native query --socket /absolute/path.sock "
                 "[--timeout-ms 1..3600000] [--progress]\n"
                 "       astmatcher-native inspect --socket /absolute/path.sock "
                 "[--timeout-ms 1..3600000]\n"
                 "       astmatcher-native capabilities < matcher-names.txt\n";
    return 2;
  };
  if (argc == 2 && std::string(argv[1]) == "capabilities") {
    return capabilities();
  }
  if (argc < 4 || std::string(argv[2]) != "--socket") {
    return usage();
  }
  const std::string command = argv[1];
  if (command != "serve" && command != "query" && command != "inspect" && command != "ping") {
    return usage();
  }
  uint32_t timeout_ms = kDefaultQueryTimeoutMs;
  std::optional<pid_t> parent_pid;
  bool progress_enabled = false;
  for (int index = 4; index < argc; ++index) {
    const std::string_view option(argv[index]);
    if (command == "query" && option == "--progress") {
      progress_enabled = true;
      continue;
    }
    if (index + 1 >= argc) return usage();
    const std::string_view input(argv[++index]);
    if ((command == "query" || command == "inspect") && option == "--timeout-ms") {
      const auto [end, error] =
          std::from_chars(input.data(), input.data() + input.size(), timeout_ms);
      if (error != std::errc{} || end != input.data() + input.size() ||
          timeout_ms == 0 || timeout_ms > kMaximumQueryTimeoutMs) {
        std::cerr << "--timeout-ms must be an integer from 1 to 3600000\n";
        return 2;
      }
    } else if (command == "serve" && option == "--parent-pid") {
      uint64_t parsed_pid = 0;
      const auto [end, error] =
          std::from_chars(input.data(), input.data() + input.size(), parsed_pid);
      if (error != std::errc{} || end != input.data() + input.size() ||
          parsed_pid == 0 ||
          parsed_pid > static_cast<uint64_t>(std::numeric_limits<pid_t>::max())) {
        std::cerr << "--parent-pid must be a positive process ID\n";
        return 2;
      }
      parent_pid = static_cast<pid_t>(parsed_pid);
    } else {
      return usage();
    }
  }
  const std::string socket_path = argv[3];
  if (!valid_socket_path(socket_path)) {
    return 2;
  }
  if (command == "serve") {
    return serve(socket_path, parent_pid);
  }
  if (command == "query") {
    return query(socket_path, timeout_ms, progress_enabled);
  }
  return command == "inspect" ? inspect(socket_path, timeout_ms) : ping(socket_path);
}
