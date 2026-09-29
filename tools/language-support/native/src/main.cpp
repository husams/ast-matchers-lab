#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

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
#include <filesystem>
#include <fcntl.h>
#include <functional>
#include <poll.h>
#include <spawn.h>
#include <signal.h>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/un.h>
#include <unistd.h>

#if defined(__GLIBC__)
#include <features.h>
#if __GLIBC_PREREQ(2, 34)
#define ASTMATCHER_HAVE_SPAWN_CLOSEFROM 1
#endif
#endif

extern char **environ;

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

volatile sig_atomic_t client_cancelled = 0;

void record_client_signal(int) { client_cancelled = 1; }

template <typename Options> void include_default_json_fields(Options &options) {
  if constexpr (requires(Options &value) {
                  value.always_print_fields_with_no_presence;
                }) {
    options.always_print_fields_with_no_presence = true;
  } else {
    options.always_print_primitive_fields = true;
  }
}

bool read_all(int descriptor, void *buffer, size_t size) {
  auto *bytes = static_cast<char *>(buffer);
  size_t offset = 0;
  while (offset < size) {
    const ssize_t count = ::read(descriptor, bytes + offset, size - offset);
    if (count == 0) return false;
    if (count < 0) {
      if (errno == EINTR) continue;
      return false;
    }
    offset += static_cast<size_t>(count);
  }
  return true;
}

bool write_all(int descriptor, const void *buffer, size_t size) {
  const auto *bytes = static_cast<const char *>(buffer);
  size_t offset = 0;
  while (offset < size) {
    const ssize_t count = ::write(descriptor, bytes + offset, size - offset);
    if (count < 0) {
      if (errno == EINTR) continue;
      return false;
    }
    offset += static_cast<size_t>(count);
  }
  return true;
}

bool read_worker_message(int descriptor, std::string &message) {
  uint8_t header[4];
  if (!read_all(descriptor, header, sizeof(header))) return false;
  const uint32_t size = (static_cast<uint32_t>(header[0]) << 24) |
                        (static_cast<uint32_t>(header[1]) << 16) |
                        (static_cast<uint32_t>(header[2]) << 8) |
                        static_cast<uint32_t>(header[3]);
  if (size > kMaximumMessageBytes) return false;
  message.resize(size);
  return read_all(descriptor, message.data(), message.size());
}

bool write_worker_message(int descriptor, const std::string &message) {
  if (message.size() > kMaximumMessageBytes) return false;
  const uint32_t size = static_cast<uint32_t>(message.size());
  const uint8_t header[] = {static_cast<uint8_t>(size >> 24),
                            static_cast<uint8_t>(size >> 16),
                            static_cast<uint8_t>(size >> 8),
                            static_cast<uint8_t>(size)};
  return write_all(descriptor, header, sizeof(header)) &&
         write_all(descriptor, message.data(), message.size());
}

bool send_worker_request(int descriptor, const std::string &message,
                         grpc::ServerContext *context) {
  if (message.size() > kMaximumMessageBytes) return false;
  const uint32_t size = static_cast<uint32_t>(message.size());
  const uint8_t header[] = {static_cast<uint8_t>(size >> 24),
                            static_cast<uint8_t>(size >> 16),
                            static_cast<uint8_t>(size >> 8),
                            static_cast<uint8_t>(size)};
  std::string framed(reinterpret_cast<const char *>(header), sizeof(header));
  framed.append(message);
  const int flags = fcntl(descriptor, F_GETFL, 0);
  if (flags < 0 || fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) < 0)
    return false;
  size_t offset = 0;
  while (offset < framed.size()) {
    if (context->IsCancelled()) return false;
    pollfd writable{descriptor, POLLOUT, 0};
    const int ready = poll(&writable, 1, 100);
    if (ready < 0) {
      if (errno == EINTR) continue;
      return false;
    }
    if (ready == 0) continue;
    if (writable.revents & (POLLERR | POLLHUP | POLLNVAL)) return false;
    if (!(writable.revents & POLLOUT)) continue;
    int send_flags = 0;
#ifdef MSG_NOSIGNAL
    send_flags |= MSG_NOSIGNAL;
#endif
    const ssize_t count = ::send(descriptor, framed.data() + offset,
                                 framed.size() - offset, send_flags);
    if (count < 0) {
      if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
      return false;
    }
    if (count == 0) return false;
    offset += static_cast<size_t>(count);
  }
  return !context->IsCancelled();
}

// ClangTool::run() is synchronous and cannot observe gRPC cancellation. Run
// each translation unit in a fresh executable process so the RPC handler can
// terminate and reap Clang even while it is blocked in the preprocessor.
grpc::Status run_worker(const std::string &executable, std::string_view operation,
                        const google::protobuf::MessageLite &request,
                        std::string &serialized_reply,
                        grpc::ServerContext *context,
                        const std::function<bool(uint64_t)> &report_progress = {}) {
  std::string serialized_request;
  if (!request.SerializeToString(&serialized_request) ||
      serialized_request.size() > kMaximumMessageBytes) {
    return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT,
                        "request is too large to process");
  }
  int sockets[2];
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) != 0) {
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "could not create Clang worker channel");
  }
#ifdef SO_NOSIGPIPE
  const int no_sigpipe = 1;
  setsockopt(sockets[0], SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe,
             sizeof(no_sigpipe));
  setsockopt(sockets[1], SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe,
             sizeof(no_sigpipe));
#endif
  for (int descriptor : sockets) {
    const int descriptor_flags = fcntl(descriptor, F_GETFD, 0);
    if (descriptor_flags < 0 ||
        fcntl(descriptor, F_SETFD, descriptor_flags | FD_CLOEXEC) < 0) {
      close(sockets[0]);
      close(sockets[1]);
      return grpc::Status(grpc::StatusCode::INTERNAL,
                          "could not protect Clang worker channel");
    }
  }
  const std::string operation_argument(operation);
  char worker_flag[] = "--worker";
  char descriptor_argument[] = "3";
  char *worker_arguments[] = {const_cast<char *>(executable.c_str()),
                              worker_flag, descriptor_argument,
                              const_cast<char *>(operation_argument.c_str()),
                              nullptr};
  posix_spawn_file_actions_t actions;
  if (posix_spawn_file_actions_init(&actions) != 0) {
    close(sockets[0]);
    close(sockets[1]);
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "could not initialize Clang worker process");
  }
  int spawn_error = posix_spawn_file_actions_addclose(&actions, sockets[0]);
  for (int descriptor = 0; spawn_error == 0 && descriptor <= 2; ++descriptor)
    spawn_error = posix_spawn_file_actions_adddup2(&actions, descriptor,
                                                  descriptor);
  if (spawn_error == 0)
    spawn_error = posix_spawn_file_actions_adddup2(&actions, sockets[1], 3);
#if defined(ASTMATCHER_HAVE_SPAWN_CLOSEFROM)
  if (spawn_error == 0)
    spawn_error = posix_spawn_file_actions_addclosefrom_np(&actions, 4);
#elif !defined(__APPLE__)
  // POSIX fallback for Unix platforms without a close-from spawn action.
  const long maximum_descriptor = sysconf(_SC_OPEN_MAX);
  for (int descriptor = 4;
       spawn_error == 0 && descriptor < maximum_descriptor; ++descriptor) {
    if (descriptor == sockets[0] || descriptor == sockets[1]) continue;
    spawn_error = posix_spawn_file_actions_addclose(&actions, descriptor);
  }
#endif
  posix_spawnattr_t attributes;
  posix_spawnattr_t *attribute_pointer = nullptr;
#ifdef POSIX_SPAWN_CLOEXEC_DEFAULT
  if (spawn_error == 0) {
    spawn_error = posix_spawnattr_init(&attributes);
    if (spawn_error == 0) {
      spawn_error = posix_spawnattr_setflags(&attributes,
                                             POSIX_SPAWN_CLOEXEC_DEFAULT);
      attribute_pointer = &attributes;
    }
  }
#endif
  pid_t child = -1;
  if (spawn_error == 0)
    spawn_error = posix_spawn(&child, executable.c_str(), &actions,
                              attribute_pointer, worker_arguments, environ);
  posix_spawn_file_actions_destroy(&actions);
#ifdef POSIX_SPAWN_CLOEXEC_DEFAULT
  if (attribute_pointer) posix_spawnattr_destroy(&attributes);
#endif
  if (spawn_error != 0) {
    close(sockets[0]);
    close(sockets[1]);
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "could not start Clang worker process");
  }
  close(sockets[1]);
  if (!send_worker_request(sockets[0], serialized_request, context)) {
    const bool cancelled = context->IsCancelled();
    kill(child, SIGKILL);
    close(sockets[0]);
    while (waitpid(child, nullptr, 0) < 0 && errno == EINTR) {}
    if (cancelled) {
      return grpc::Status(grpc::StatusCode::CANCELLED,
                          "query cancelled by client or deadline");
    }
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "could not send request to Clang worker");
  }
  const int previous_flags = fcntl(sockets[0], F_GETFL, 0);
  if (previous_flags < 0 ||
      fcntl(sockets[0], F_SETFL, previous_flags | O_NONBLOCK) < 0) {
    kill(child, SIGKILL);
    close(sockets[0]);
    while (waitpid(child, nullptr, 0) < 0 && errno == EINTR) {}
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "could not configure Clang worker channel");
  }
  bool eof = false;
  bool failed = false;
  int child_status = 0;
  bool child_exited = false;
  auto next_report = std::chrono::steady_clock::now() + std::chrono::seconds(1);
  const auto started = std::chrono::steady_clock::now();
  uint8_t chunk[16384];
  while (!eof) {
    if (context->IsCancelled()) {
      kill(child, SIGKILL);
      close(sockets[0]);
      while (waitpid(child, nullptr, 0) < 0 && errno == EINTR) {}
      return grpc::Status(grpc::StatusCode::CANCELLED,
                          "query cancelled by client or deadline");
    }
    const auto now = std::chrono::steady_clock::now();
    if (report_progress && now >= next_report) {
      const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                               now - started)
                               .count();
      if (!report_progress(static_cast<uint64_t>(elapsed))) {
        kill(child, SIGKILL);
        close(sockets[0]);
        while (waitpid(child, nullptr, 0) < 0 && errno == EINTR) {}
        return grpc::Status(grpc::StatusCode::CANCELLED,
                            "progress client disconnected");
      }
      next_report = now + std::chrono::seconds(1);
    }
    pollfd descriptor{sockets[0], POLLIN | POLLHUP, 0};
    const int polled = poll(&descriptor, 1, 100);
    if (polled < 0 && errno != EINTR) {
      failed = true;
      break;
    }
    if (polled > 0 && (descriptor.revents & (POLLIN | POLLHUP | POLLERR))) {
      for (;;) {
        const ssize_t count = ::read(sockets[0], chunk, sizeof(chunk));
        if (count > 0) {
          if (serialized_reply.size() + static_cast<size_t>(count) >
              kMaximumMessageBytes + sizeof(uint32_t)) {
            failed = true;
            break;
          }
          serialized_reply.append(reinterpret_cast<char *>(chunk), count);
          continue;
        }
        if (count == 0) eof = true;
        else if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
          failed = true;
        break;
      }
    }
    if (failed) break;
    if (!child_exited) {
      const pid_t result = waitpid(child, &child_status, WNOHANG);
      if (result == child) child_exited = true;
      else if (result < 0 && errno != EINTR) {
        failed = true;
        break;
      }
    }
    if (child_exited && !eof && polled == 0) {
      failed = true;
      break;
    }
  }
  if (!child_exited) {
    // Give an otherwise successful worker a short window to finish its exit
    // after closing the reply socket; malformed/failed IPC is killed at once.
    for (int attempt = 0; !failed && attempt < 10; ++attempt) {
      const pid_t result = waitpid(child, &child_status, WNOHANG);
      if (result == child) {
        child_exited = true;
        break;
      }
      if (result < 0 && errno != EINTR) {
        failed = true;
        break;
      }
      if (result == 0) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (!child_exited) {
      // EOF or an IPC error without a completed child cannot produce a valid
      // response; never wait indefinitely for a worker that stopped replying.
      kill(child, SIGKILL);
    }
  }
  close(sockets[0]);
  if (!child_exited) {
    while (waitpid(child, &child_status, 0) < 0) {
      if (errno == EINTR) continue;
      failed = true;
      break;
    }
  }
  if (failed || !WIFEXITED(child_status) || WEXITSTATUS(child_status) != 0 ||
      serialized_reply.size() < sizeof(uint32_t)) {
    std::string reason = "Clang worker failed before returning a reply";
    if (failed) reason += " (IPC failure)";
    else if (WIFSIGNALED(child_status))
      reason += " (signal " + std::to_string(WTERMSIG(child_status)) + ")";
    else if (WIFEXITED(child_status))
      reason += " (exit " + std::to_string(WEXITSTATUS(child_status)) + ")";
    reason += " after " + std::to_string(serialized_reply.size()) + " bytes";
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        std::move(reason));
  }
  const auto *bytes = reinterpret_cast<const uint8_t *>(serialized_reply.data());
  const uint32_t size = (static_cast<uint32_t>(bytes[0]) << 24) |
                        (static_cast<uint32_t>(bytes[1]) << 16) |
                        (static_cast<uint32_t>(bytes[2]) << 8) |
                        static_cast<uint32_t>(bytes[3]);
  if (size > kMaximumMessageBytes || serialized_reply.size() != size + 4) {
    return grpc::Status(grpc::StatusCode::INTERNAL,
                        "Clang worker returned an invalid reply");
  }
  serialized_reply.erase(0, 4);
  return grpc::Status::OK;
}

class ClientSignalCancellation {
public:
  explicit ClientSignalCancellation(grpc::ClientContext &context)
      : context_(context) {
    client_cancelled = 0;
    struct sigaction action {};
    action.sa_handler = record_client_signal;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0;
    sigaction(SIGTERM, &action, &old_term_);
    sigaction(SIGINT, &action, &old_int_);
    monitor_ = std::thread([this] {
      while (!stopping_.load()) {
        if (client_cancelled) {
          context_.TryCancel();
          return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
    });
  }

  ~ClientSignalCancellation() {
    stopping_.store(true);
    if (monitor_.joinable()) monitor_.join();
    sigaction(SIGTERM, &old_term_, nullptr);
    sigaction(SIGINT, &old_int_, nullptr);
  }

private:
  grpc::ClientContext &context_;
  std::atomic<bool> stopping_{false};
  std::thread monitor_;
  struct sigaction old_term_ {};
  struct sigaction old_int_ {};
};

class WorkerParentWatchdog {
public:
  WorkerParentWatchdog() : parent_(getppid()), thread_([this] {
    while (!stopping_.load()) {
      if (getppid() != parent_) std::_Exit(0);
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
  }) {}

  ~WorkerParentWatchdog() {
    stopping_.store(true);
    if (thread_.joinable()) thread_.join();
  }

private:
  pid_t parent_;
  std::atomic<bool> stopping_{false};
  std::thread thread_;
};

int worker(int descriptor, std::string_view operation) {
  std::string input;
  if (!read_worker_message(descriptor, input)) return 2;
  std::string output;
  if (operation == "run") {
    astmatcher::native::v1::RunRequest request;
    astmatcher::native::v1::RunReply reply;
    if (!request.ParseFromString(input)) return 2;
    WorkerParentWatchdog watchdog;
    reply = astmatcher::native::run_match_request(request);
    if (!reply.SerializeToString(&output)) return 3;
  } else if (operation == "inspect") {
    astmatcher::native::v1::InspectRecordRequest request;
    astmatcher::native::v1::InspectRecordReply reply;
    if (!request.ParseFromString(input)) return 2;
    WorkerParentWatchdog watchdog;
    reply = astmatcher::native::inspect_record_request(request);
    if (!reply.SerializeToString(&output)) return 3;
  } else {
    return 2;
  }
  return write_worker_message(descriptor, output) ? 0 : 3;
}

class MatcherService final
    : public astmatcher::native::v1::MatcherService::Service {
public:
  explicit MatcherService(std::string executable)
      : executable_(std::move(executable)) {}

  grpc::Status Ping(grpc::ServerContext *,
                    const astmatcher::native::v1::PingRequest *,
                    astmatcher::native::v1::PingReply *reply) override {
    reply->set_version("1");
    reply->set_compiler_path(ASTMATCHER_COMPILER_PATH);
    return grpc::Status::OK;
  }

  grpc::Status Run(grpc::ServerContext *context,
                   const astmatcher::native::v1::RunRequest *request,
                   astmatcher::native::v1::RunReply *reply) override {
    // Clang's dynamic registry and source manager are not documented as safe
    // for concurrent tooling invocations in one process.
    const std::lock_guard<std::mutex> guard(mutex_);
    std::string output;
    const auto status = run_worker(executable_, "run", *request, output, context);
    if (!status.ok()) return status;
    if (!reply->ParseFromString(output)) {
      return grpc::Status(grpc::StatusCode::INTERNAL,
                          "Clang worker returned an invalid query reply");
    }
    return grpc::Status::OK;
  }

  grpc::Status InspectRecord(
      grpc::ServerContext *context,
      const astmatcher::native::v1::InspectRecordRequest *request,
      astmatcher::native::v1::InspectRecordReply *reply) override {
    const std::lock_guard<std::mutex> guard(mutex_);
    std::string output;
    const auto status = run_worker(executable_, "inspect", *request, output,
                                   context);
    if (!status.ok()) return status;
    if (!reply->ParseFromString(output)) {
      return grpc::Status(grpc::StatusCode::INTERNAL,
                          "Clang worker returned an invalid inspection reply");
    }
    return grpc::Status::OK;
  }

  grpc::Status RunWithProgress(
      grpc::ServerContext *context,
      const astmatcher::native::v1::RunRequest *request,
      grpc::ServerWriter<astmatcher::native::v1::RunProgress> *writer) override {
    using astmatcher::native::v1::RunProgress;
    const std::lock_guard<std::mutex> guard(mutex_);
    const auto started = std::chrono::steady_clock::now();
    RunProgress initial;
    initial.set_source_path(request->source_path());
    initial.set_elapsed_ms(0);
    bool connected = writer->Write(initial);
    if (!connected) {
      return grpc::Status(grpc::StatusCode::CANCELLED,
                          "progress client disconnected");
    }
    astmatcher::native::v1::RunReply reply;
    std::string serialized;
    const auto status = run_worker(
        executable_, "run", *request, serialized, context,
        [&](uint64_t elapsed_ms) {
          if (!connected) return false;
          RunProgress progress;
          progress.set_source_path(request->source_path());
          progress.set_elapsed_ms(elapsed_ms);
          connected = writer->Write(progress);
          return connected;
        });
    if (!status.ok()) return status;
    if (!connected || !reply.ParseFromString(serialized)) {
      return grpc::Status(grpc::StatusCode::INTERNAL,
                          "Clang worker returned an invalid query reply");
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
  std::string executable_;
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

std::optional<std::string> resolve_executable(const char *argument) {
  namespace fs = std::filesystem;
  const fs::path requested(argument);
  std::vector<fs::path> candidates;
  if (requested.has_parent_path()) {
    candidates.push_back(requested);
  } else if (const char *path_environment = std::getenv("PATH")) {
    std::string_view path(path_environment);
    size_t start = 0;
    while (start <= path.size()) {
      const size_t separator = path.find(':', start);
      const std::string_view directory = path.substr(
          start, separator == std::string_view::npos ? path.size() - start
                                                     : separator - start);
      candidates.push_back((directory.empty() ? fs::path(".")
                                              : fs::path(directory)) /
                           requested);
      if (separator == std::string_view::npos) break;
      start = separator + 1;
    }
  }
  for (const auto &candidate : candidates) {
    if (access(candidate.c_str(), X_OK) != 0) continue;
    std::error_code error;
    const fs::path resolved = fs::canonical(candidate, error);
    if (!error) return resolved.string();
  }
  return std::nullopt;
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

int serve(const std::string &socket_path, std::optional<pid_t> parent_pid,
          const std::string &executable) {
  if (!clear_stale_socket(socket_path)) {
    return 1;
  }
  MatcherService service(executable);
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
  ClientSignalCancellation signal_cancellation(context);
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
  ClientSignalCancellation signal_cancellation(context);
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
  if (argc == 4 && std::string_view(argv[1]) == "--worker") {
    int descriptor = -1;
    const std::string_view input(argv[2]);
    const auto [end, error] =
        std::from_chars(input.data(), input.data() + input.size(), descriptor);
    if (error != std::errc{} || end != input.data() + input.size() ||
        descriptor < 0) {
      return 2;
    }
    return worker(descriptor, argv[3]);
  }
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
    const auto executable = resolve_executable(argv[0]);
    if (!executable) {
      std::cerr << "Could not resolve native server executable from argv[0] or PATH\n";
      return 1;
    }
    return serve(socket_path, parent_pid, *executable);
  }
  if (command == "query") {
    return query(socket_path, timeout_ms, progress_enabled);
  }
  return command == "inspect" ? inspect(socket_path, timeout_ms) : ping(socket_path);
}
