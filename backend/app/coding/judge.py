"""샌드박스 실행과 채점 (TRD §5.3~5.4).

지원자 코드는 일회용 Docker 컨테이너에서만 실행한다(네트워크 없음·읽기 전용·자원 제한·비루트). 케이스마다 컨테이너 1개.
`Sandbox` 프로토콜 뒤에 두어 테스트는 도커 없이 가짜 샌드박스로 채점 로직(판정 집계·출력 비교)을 검증한다.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.coding.problems import LANGUAGES, Case

OUTPUT_LIMIT = 64 * 1024  # stdout/stderr 각 64KB 에서 자른다
COMPILE_LIMIT_S = 10.0
MAX_SOURCE_CHARS = 50_000


class SandboxUnavailable(Exception):
    """Docker 데몬/이미지가 없다 → 503 SANDBOX_UNAVAILABLE."""


@dataclass
class RunResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: int = 0
    timed_out: bool = False
    oom: bool = False
    truncated: bool = False
    compile_error: bool = False


class Sandbox(Protocol):
    async def run(self, language: str, source: str, stdin: str, *, time_limit_s: float) -> RunResult: ...
    async def analyze(self, language: str, source: str) -> dict | None: ...


@dataclass
class CaseResult:
    index: int
    verdict: str
    runtime_ms: int = 0
    stdout: str = ""  # 샘플 케이스에만 채운다(비공개 케이스의 입출력은 응답에 담지 않는다)
    stderr: str = ""
    visible: bool = False
    truncated: bool = False


@dataclass
class Judged:
    verdict: str
    cases: list[CaseResult] = field(default_factory=list)
    runtime_ms: int = 0
    compile_log: str = ""


def normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n"))


def case_verdict(r: RunResult, expected: str) -> str:
    if r.compile_error:
        return "CE"
    if r.timed_out:
        return "TLE"
    if r.oom:
        return "MLE"
    if r.truncated:
        return "OLE"
    if r.exit_code != 0:
        return "RE"
    return "AC" if normalize(r.stdout) == normalize(expected) else "WA"


_ORDER = ("CE", "RE", "TLE", "MLE", "OLE", "WA")  # 전체 판정: 가장 심각한 것 (모두 통과해야 AC)


def overall(verdicts: list[str]) -> str:
    for v in _ORDER:
        if v in verdicts:
            return v
    return "AC"


async def judge(sandbox: Sandbox, language: str, source: str, cases: list[Case], *, visible: int, time_limit_s: float, limit_cases: int | None = None) -> Judged:
    """`limit_cases` 가 있으면 앞의 N개만 실행한다(샘플 실행 `run`). 컴파일 오류는 첫 케이스에서 확정되고 나머지는 실행하지 않는다."""
    todo = cases[:limit_cases] if limit_cases else cases
    out: list[CaseResult] = []
    log = ""
    for i, c in enumerate(todo):
        r = await sandbox.run(language, source, c.stdin, time_limit_s=time_limit_s)
        v = case_verdict(r, c.expected)
        show = i < visible
        out.append(CaseResult(i + 1, v, r.elapsed_ms, r.stdout[:OUTPUT_LIMIT] if show else "", r.stderr[:OUTPUT_LIMIT] if show or v in ("CE", "RE") else "",
                              show, r.truncated))
        if v == "CE":
            log = r.stderr[:2000]
            break
    return Judged(overall([c.verdict for c in out]), out, max((c.runtime_ms for c in out), default=0), log)


# ── Docker 구현 ───────────────────────────────────────────────────────────────
async def _read_limited(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    """limit 바이트까지만 보관하고 나머지는 버리되 끝까지 읽어(파이프가 막히지 않게) 잘림 여부를 돌려준다."""
    buf = bytearray()
    total = 0
    while chunk := await stream.read(8192):
        total += len(chunk)
        if len(buf) < limit:
            buf += chunk[: limit - len(buf)]
    return bytes(buf), total > limit


class DockerSandbox:
    """TRD §5.3 의 옵션 그대로. 이미지는 사전 빌드(`backend/sandbox/build.sh`)하며 런타임에 pull 하지 않는다."""

    def __init__(self, memory_mb: int = 128, docker_bin: str | None = None, concurrency: int = 1):
        self.memory_mb = memory_mb
        self.docker = docker_bin or shutil.which("docker") or "docker"
        self._sem = asyncio.Semaphore(concurrency)  # 16GB 예산: 동시에 하나만 실행

    def _base(self, name: str, image: str, work: Path, *, rw: bool = False) -> list[str]:
        return [self.docker, "run", "--rm", "-i", "--name", name, "--network", "none", "--memory", f"{self.memory_mb}m", "--memory-swap", f"{self.memory_mb}m",
                "--cpus", "0.5", "--pids-limit", "64", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "10001:10001", "--ulimit", "nofile=64", "--ulimit", "fsize=1048576",
                "-v", f"{work}:/work:{'rw' if rw else 'ro'}", image]

    async def _exec(self, argv: list[str], name: str, stdin: bytes, wall_s: float) -> RunResult:
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as e:
            raise SandboxUnavailable("docker not found") from e
        assert proc.stdin and proc.stdout and proc.stderr

        async def feed() -> None:
            with contextlib.suppress(Exception):
                proc.stdin.write(stdin)  # type: ignore[union-attr]
                await proc.stdin.drain()  # type: ignore[union-attr]
                proc.stdin.close()  # type: ignore[union-attr]

        async def collect() -> tuple[bytes, bool, bytes, bool, int]:
            (o, ot), (e, et), _ = await asyncio.gather(_read_limited(proc.stdout, OUTPUT_LIMIT), _read_limited(proc.stderr, OUTPUT_LIMIT), feed())  # type: ignore[arg-type]
            return o, ot, e, et, await proc.wait()

        timed_out = False
        try:
            o, ot, e, et, code = await asyncio.wait_for(collect(), wall_s)
        except asyncio.TimeoutError:
            timed_out = True
            await asyncio.create_subprocess_exec(self.docker, "kill", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)  # 이중 안전장치
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            o = e = b""
            ot = et = False
            code = -9
        elapsed = int((time.monotonic() - t0) * 1000)
        err = e.decode("utf-8", "replace")
        if code == 125 or "Unable to find image" in err or "Cannot connect to the Docker daemon" in err:
            raise SandboxUnavailable(err[:200])
        return RunResult(code, o.decode("utf-8", "replace"), err, elapsed, timed_out=timed_out, truncated=ot or et)

    async def run(self, language: str, source: str, stdin: str, *, time_limit_s: float = 3.0) -> RunResult:
        spec = LANGUAGES[language]
        async with self._sem:
            work = Path(tempfile.mkdtemp(prefix="judge-"))
            try:
                os.chmod(work, 0o755)  # 컨테이너의 비루트(10001)가 읽을 수 있어야 한다
                (work / spec["file"]).write_text(source, encoding="utf-8")
                os.chmod(work / spec["file"], 0o644)
                name = f"judge-{uuid.uuid4().hex[:12]}"
                limit = f"{int(time_limit_s)}"
                if language == "java":
                    os.chmod(work, 0o777)  # 컴파일 산출물(.class)을 쓰는 단계만 rw
                    c = await self._exec([*self._base(name + "c", spec["image"], work, rw=True), "timeout", "-s", "KILL", str(int(COMPILE_LIMIT_S)),
                                          "javac", "-d", "/work", "/work/Main.java"], name + "c", b"", COMPILE_LIMIT_S + 1)
                    if c.exit_code != 0:
                        c.compile_error = not c.timed_out
                        return c
                    cmd = ["timeout", "-s", "KILL", limit, "java", "-Xmx96m", "-cp", "/work", "Main"]
                elif language == "python":
                    cmd = ["timeout", "-s", "KILL", limit, "python", "/work/main.py"]
                else:
                    cmd = ["timeout", "-s", "KILL", limit, "node", "/work/main.js"]
                r = await self._exec([*self._base(name, spec["image"], work), *cmd], name, stdin.encode("utf-8"), time_limit_s + 1.0)
                if language == "python" and r.exit_code != 0 and "SyntaxError" in r.stderr:
                    r.compile_error = True  # 파이썬의 구문 오류는 컴파일 오류로 취급
                if not r.timed_out and r.exit_code == 137:  # SIGKILL: timeout(-s KILL) 이면 시간이 한계에 가깝고, 아니면 OOM kill
                    if r.elapsed_ms >= time_limit_s * 1000 * 0.9:
                        r.timed_out = True
                    else:
                        r.oom = True
                return r
            finally:
                shutil.rmtree(work, ignore_errors=True)

    async def analyze(self, language: str, source: str) -> dict | None:
        from app.coding.analysis import analyze_source

        return await analyze_source(self, language, source)

    async def analyze_python_in_container(self, source: str) -> dict | None:
        """ruff + radon 을 별도 분석 컨테이너(네트워크 차단)에서 실행한다 (TRD §5.5)."""
        spec = LANGUAGES["python"]
        async with self._sem:
            work = Path(tempfile.mkdtemp(prefix="analyze-"))
            try:
                os.chmod(work, 0o755)
                (work / "main.py").write_text(source, encoding="utf-8")
                os.chmod(work / "main.py", 0o644)
                name = f"judge-an-{uuid.uuid4().hex[:10]}"
                script = ("ruff check --output-format json --no-cache /work/main.py; echo '@@'; radon cc -j /work/main.py; echo '@@'; radon mi -j /work/main.py")
                r = await self._exec([*self._base(name, spec["image"], work), "sh", "-c", script], name, b"", 15.0)
                return {"raw": r.stdout} if r.exit_code in (0, 1) else None
            finally:
                shutil.rmtree(work, ignore_errors=True)
