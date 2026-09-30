"""Async process and private-socket bridge to astmatcher-native."""

import asyncio
import json
import math
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from .models import MatcherQuery, RunResult, ServerStatus


class MatcherError(RuntimeError):
    """The native matcher executable or service could not complete an operation."""


class MatcherClient:
    """Own a private native server; connection and lifetime are automatic.

    Use `async with MatcherClient() as client` and await `client.run(query)`.
    The executable is found through ASTMATCHER_NATIVE, a local build, or PATH.
    """

    def __init__(self, *, binary: str | Path | None = None) -> None:
        self._binary_override = str(binary) if binary is not None else None
        self._binary: str | None = None
        self._lock = asyncio.Lock()
        self._server: asyncio.subprocess.Process | None = None
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._socket: str | None = None
        self._log = None
        self._closed = False

    async def __aenter__(self) -> "MatcherClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _find_binary(self) -> str:
        if self._binary is not None:
            return self._binary
        configured = self._binary_override or os.environ.get("ASTMATCHER_NATIVE")
        candidates = (
            [configured] if configured else [
                str(Path(__file__).resolve().parents[3] / "native" / "build"
                    / "astmatcher-native"),
                "astmatcher-native",
            ]
        )
        for candidate in candidates:
            path = shutil.which(candidate) or candidate
            if os.path.isfile(path) and os.access(path, os.X_OK):
                self._binary = str(Path(path).resolve())
                return self._binary
        raise MatcherError(
            "astmatcher-native is unavailable; install the native service "
            "or set ASTMATCHER_NATIVE"
        )

    async def _ping(self) -> ServerStatus:
        if self._server is None or self._server.returncode is not None or not self._socket:
            return ServerStatus("stopped")
        probe: asyncio.subprocess.Process | None = None
        try:
            probe = await asyncio.create_subprocess_exec(
                self._find_binary(), "ping", "--socket", self._socket,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(probe.communicate(), timeout=1.0)
            if probe.returncode:
                return ServerStatus("unavailable", detail=stderr.decode(
                    "utf-8", "replace").strip()[:500])
            reply = json.loads(stdout)
            if not isinstance(reply, dict):
                raise ValueError("ping response was not an object")
            return ServerStatus(
                "ready",
                version=str(reply.get("version", "")),
                compiler_path=str(reply.get("compilerPath", "")),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ServerStatus("unavailable", detail=str(exc))
        except TimeoutError:
            probe.kill()
            await probe.wait()
            return ServerStatus("unavailable", detail="native server ping timed out")
        except asyncio.CancelledError:
            if probe is not None and probe.returncode is None:
                probe.kill()
                await probe.wait()
            raise

    async def status(self) -> ServerStatus:
        """Report the server's live readiness, version, and compiler path."""
        try:
            self._find_binary()
        except MatcherError as exc:
            return ServerStatus("unavailable", detail=str(exc))
        async with self._lock:
            return await self._ping()

    async def watch_status(self, interval: float = 1.0) -> AsyncIterator[ServerStatus]:
        """Yield a status when it changes, until the client is closed."""
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("interval must be positive and finite")
        previous: ServerStatus | None = None
        while not self._closed:
            current = await self.status()
            if current != previous:
                yield current
                previous = current
            await asyncio.sleep(interval)

    async def start(self) -> ServerStatus:
        """Start the private service if needed and wait until it answers ping."""
        if self._closed:
            raise MatcherError("matcher client is closed")
        async with self._lock:
            if self._server is not None and self._server.returncode is None:
                status = await self._ping()
                if status.ready:
                    return status
            await self._stop_locked()
            binary = self._find_binary()
            # A short /tmp path fits macOS's Unix socket length limit.
            self._directory = tempfile.TemporaryDirectory(prefix="am-sdk-", dir="/tmp")
            self._socket = str(Path(self._directory.name) / "s")
            self._log = open(Path(self._directory.name) / "server.log", "w+b")
            try:
                self._server = await asyncio.create_subprocess_exec(
                    binary, "serve", "--socket", self._socket,
                    "--parent-pid", str(os.getpid()),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=self._log,
                )
                deadline = asyncio.get_running_loop().time() + 5.0
                while asyncio.get_running_loop().time() < deadline:
                    if self._server.returncode is not None:
                        break
                    if os.path.exists(self._socket):
                        status = await self._ping()
                        if status.ready:
                            return status
                    await asyncio.sleep(0.05)
                self._log.seek(0)
                detail = self._log.read(2000).decode("utf-8", "replace").strip()
                raise MatcherError("native matcher server did not become ready"
                                   + (f": {detail}" if detail else ""))
            except BaseException:
                await self._stop_locked()
                raise

    async def run(self, query: MatcherQuery, *, timeout: float = 120.0) -> RunResult:
        """Run a declarative query without choosing a socket or starting a server."""
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("timeout must be between 0 and 3600 seconds")
        await self.start()
        request = await asyncio.to_thread(query.request)
        process = await asyncio.create_subprocess_exec(
            self._find_binary(), "query", "--socket", self._socket,
            "--timeout-ms", str(max(1, math.ceil(timeout * 1000))),
            cwd=str(request["workingDirectory"]),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(request).encode()),
                timeout=timeout + 1.0,
            )
        except (TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            message = stderr.decode("utf-8", "replace").strip()[:2000]
            raise MatcherError(message or f"native matcher exited with {process.returncode}")
        try:
            reply = json.loads(stdout)
            if not isinstance(reply, dict):
                raise ValueError("native matcher returned a non-object response")
            return RunResult.from_reply(reply)
        except (ValueError, TypeError, KeyError) as exc:
            raise MatcherError("native matcher returned an invalid response") from exc

    async def _stop_locked(self) -> None:
        server = self._server
        self._server = None
        if server is not None and server.returncode is None:
            server.terminate()
            try:
                await asyncio.wait_for(server.wait(), timeout=2.0)
            except TimeoutError:
                server.kill()
                await server.wait()
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self._socket = None

    async def close(self) -> None:
        """Stop the owned service and remove its private socket."""
        self._closed = True
        async with self._lock:
            await self._stop_locked()
