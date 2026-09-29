"""Small stdlib-only process bridge to the native gRPC matcher server.

The native executable owns protobuf and gRPC. Python sends protobuf JSON to
its ``query`` command, which talks to one private, long-lived Unix socket.
"""

from __future__ import annotations

import atexit
import json
import math
import os
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable


class NativeClientError(RuntimeError):
    """The native matcher server or its query client could not run."""


def native_binary_path(configured: str | None = None) -> str:
    """Find the executable shipped with the LSP, built locally, or on PATH."""
    configured = configured or os.environ.get("ASTMATCHER_NATIVE")
    if configured:
        candidate = shutil.which(configured) or configured
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
        raise NativeClientError(f"native matcher executable not found: {configured}")

    support_dir = Path(__file__).resolve().parents[2]
    candidates = [
        support_dir / "native" / "build" / "astmatcher-native",
        support_dir / "native" / "astmatcher-native",
        Path(__file__).resolve().parents[1] / "bin" / "astmatcher-native",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    found = shutil.which("astmatcher-native")
    if found:
        return str(Path(found).resolve())
    raise NativeClientError(
        "astmatcher-native is unavailable; build the native server or set ASTMATCHER_NATIVE")


class NativeClient:
    """Own one server process; spawn a short-lived CLI bridge for each Run RPC."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self._lock = threading.Lock()
        self._directory: str | None = None
        self._socket: str | None = None
        self._server: subprocess.Popen | None = None
        self._server_log = None
        self._binary_stamp: tuple[int, int] | None = None
        self._compiler_path: str | None = None

    @property
    def compiler_path(self) -> str | None:
        """Compiler reported by the running server's Ping response."""
        self._ensure_server()
        return self._compiler_path

    def _stamp(self) -> tuple[int, int]:
        try:
            stat = os.stat(self.binary)
        except OSError as exc:
            raise NativeClientError(f"native matcher executable is unavailable: {exc}") from exc
        return stat.st_size, stat.st_mtime_ns

    def _ensure_server(self) -> str:
        with self._lock:
            stamp = self._stamp()
            if (self._server is not None and self._server.poll() is None and
                    self._socket and self._binary_stamp == stamp):
                return self._socket
            self._stop_locked()
            # Darwin's sockaddr_un.sun_path is short. /tmp keeps this below 104 bytes.
            directory = tempfile.mkdtemp(prefix="am-", dir="/tmp")
            socket_path = os.path.join(directory, "s")
            server = None
            log_file = open(os.path.join(directory, "server.log"), "w+b")
            try:
                try:
                    server = subprocess.Popen(
                        [self.binary, "serve", "--socket", socket_path,
                         "--parent-pid", str(os.getpid())],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=log_file)
                except OSError as exc:
                    raise NativeClientError(f"cannot start native matcher server: {exc}") from exc
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        log_file.seek(0)
                        reason = log_file.read(2000).decode("utf-8", "replace").strip()
                        raise NativeClientError(
                            f"native matcher server exited with code {server.returncode}"
                            + (f": {reason}" if reason else ""))
                    if os.path.exists(socket_path):
                        try:
                            probe = subprocess.run(
                                [self.binary, "ping", "--socket", socket_path],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=0.5, check=False)
                        except subprocess.TimeoutExpired:
                            probe = None
                        except OSError as exc:
                            raise NativeClientError(
                                f"cannot check native matcher server: {exc}") from exc
                        if probe is not None and probe.returncode == 0:
                            try:
                                ping_reply = json.loads(probe.stdout)
                            except (TypeError, json.JSONDecodeError):
                                ping_reply = {}
                            self._directory, self._socket, self._server = (
                                directory, socket_path, server)
                            self._server_log = log_file
                            self._binary_stamp = stamp
                            compiler = (ping_reply.get("compilerPath")
                                        if isinstance(ping_reply, dict) else None)
                            self._compiler_path = (compiler if isinstance(compiler, str) and
                                                   os.path.isabs(compiler) else None)
                            return socket_path
                    time.sleep(0.05)
                log_file.seek(0)
                reason = log_file.read(2000).decode("utf-8", "replace").strip()
                raise NativeClientError("native matcher server did not become ready"
                                        + (f": {reason}" if reason else ""))
            except Exception:
                if server is not None and server.poll() is None:
                    server.kill()
                    server.wait()
                log_file.close()
                shutil.rmtree(directory, ignore_errors=True)
                raise

    def run(self, request: dict, *, cwd: str, timeout: float,
            on_start: Callable[[subprocess.Popen], None] | None = None,
            on_progress: Callable[[dict], None] | None = None,
            cancelled: threading.Event | None = None
            ) -> tuple[dict, list[str], int, str]:
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise NativeClientError("native matcher timeout must be between 0 and 3600 seconds")
        socket_path = self._ensure_server()
        timeout_ms = max(1, math.ceil(timeout * 1000))
        command = [self.binary, "query", "--socket", socket_path,
                   "--timeout-ms", str(timeout_ms), "--progress"]
        stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        try:
            proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=stderr_file)
        except OSError as exc:
            stderr_file.close()
            raise NativeClientError(f"cannot start native matcher client: {exc}") from exc
        if on_start:
            on_start(proc)
        pending = bytearray()
        reply = None
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None and proc.stdin is not None
        selector.register(proc.stdout, selectors.EVENT_READ)
        try:
            proc.stdin.write(json.dumps(request).encode("utf-8"))
            proc.stdin.close()
            deadline = time.monotonic() + timeout + 1.0
            while selector.get_map():
                if cancelled is not None and cancelled.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    if proc.stdout and not proc.stdout.closed:
                        proc.stdout.close()
                    stderr_file.close()
                    raise NativeClientError("native matcher query cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                for key, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    pending.extend(chunk)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending[:] = rest
                        if not line:
                            continue
                        item = json.loads(line)
                        if isinstance(item, dict) and isinstance(item.get("progress"), dict):
                            if on_progress:
                                on_progress(item["progress"])
                        else:
                            reply = item
                if proc.poll() is not None and not selector.get_map():
                    break
            if pending.strip():
                reply = json.loads(pending)
            return_code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            proc.kill()
            proc.wait()
            proc.stdout.close()
            stderr_file.close()
            self.close()
            raise NativeClientError(f"native matcher timed out after {timeout:g}s") from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            proc.kill()
            proc.wait()
            proc.stdout.close()
            stderr_file.close()
            raise NativeClientError(f"native matcher returned invalid progress data: {exc}") from exc
        finally:
            selector.close()
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()
        stderr_file.seek(0)
        stderr = stderr_file.read()
        stderr_file.close()
        if return_code:
            if "deadline" in stderr.lower() or "timed out" in stderr.lower():
                self.close()
                raise NativeClientError(f"native matcher timed out after {timeout:g}s")
            raise NativeClientError(
                f"native matcher client exited with code {return_code}: {stderr.strip()[:2000]}")
        if not isinstance(reply, dict):
            raise NativeClientError("native matcher returned a non-object response")
        return reply, command, return_code, stderr

    def inspect(self, request: dict, *, cwd: str, timeout: float) -> dict:
        """Inspect a source-located record through the existing native server."""
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise NativeClientError("native matcher timeout must be between 0 and 3600 seconds")
        socket_path = self._ensure_server()
        command = [self.binary, "inspect", "--socket", socket_path,
                   "--timeout-ms", str(max(1, math.ceil(timeout * 1000)))]
        try:
            proc = subprocess.run(command, cwd=cwd, input=json.dumps(request).encode("utf-8"),
                                  capture_output=True, timeout=timeout + 1, check=False)
        except subprocess.TimeoutExpired as exc:
            self.close()
            raise NativeClientError(f"native matcher timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise NativeClientError(f"cannot start native matcher client: {exc}") from exc
        if proc.returncode:
            message = proc.stderr.decode("utf-8", "replace").strip()[:2000]
            raise NativeClientError(message or
                                    f"native matcher client exited with code {proc.returncode}")
        try:
            reply = json.loads(proc.stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise NativeClientError("native matcher returned invalid record data") from exc
        if not isinstance(reply, dict):
            raise NativeClientError("native matcher returned a non-object response")
        return reply

    def _stop_locked(self) -> None:
        server = self._server
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        self._server = None
        self._socket = None
        self._binary_stamp = None
        self._compiler_path = None
        if self._server_log is not None:
            self._server_log.close()
            self._server_log = None
        if self._directory:
            shutil.rmtree(self._directory, ignore_errors=True)
            self._directory = None

    def close(self) -> None:
        with self._lock:
            self._stop_locked()


_GLOBAL_LOCK = threading.Lock()
_GLOBAL_CLIENT: NativeClient | None = None


def get_client(configured: str | None = None) -> NativeClient:
    """Reuse the server across requests, restarting only if the binary changes."""
    global _GLOBAL_CLIENT
    binary = native_binary_path(configured)
    with _GLOBAL_LOCK:
        if _GLOBAL_CLIENT is None or _GLOBAL_CLIENT.binary != binary:
            if _GLOBAL_CLIENT is not None:
                _GLOBAL_CLIENT.close()
            _GLOBAL_CLIENT = NativeClient(binary)
        return _GLOBAL_CLIENT


def close_global() -> None:
    global _GLOBAL_CLIENT
    with _GLOBAL_LOCK:
        if _GLOBAL_CLIENT is not None:
            _GLOBAL_CLIENT.close()
            _GLOBAL_CLIENT = None


atexit.register(close_global)
