"""실제 Docker 샌드박스 검증 (TRD §5.3). docker 와 사전 빌드된 sandbox-* 이미지가 없으면 건너뛴다 — `backend/sandbox/build.sh`."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from app.coding.judge import DockerSandbox, case_verdict


def _has(image: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _has("sandbox-python:1"), reason="sandbox-python:1 이미지가 없음 (backend/sandbox/build.sh)")
SB = DockerSandbox()
LIMIT = 3.0


async def verdict(language: str, source: str, stdin: str = "", expected: str = "") -> str:
    return case_verdict(await SB.run(language, source, stdin, time_limit_s=LIMIT), expected)


async def test_python_accepts_correct_solution_and_wrong_answer():
    src = "a,b=map(int,input().split());print(a+b)"
    assert await verdict("python", src, "1 2\n", "3") == "AC"
    assert await verdict("python", src, "1 2\n", "4") == "WA"


async def test_runtime_error_syntax_error_and_infinite_loop():
    assert await verdict("python", "1/0") == "RE"
    r = await SB.run("python", "def (:", "", time_limit_s=LIMIT)
    assert case_verdict(r, "") == "CE"
    r = await SB.run("python", "while True: pass", "", time_limit_s=LIMIT)
    assert case_verdict(r, "") == "TLE" and r.elapsed_ms < 6000


async def test_output_flood_is_truncated_and_memory_bomb_is_killed():
    r = await SB.run("python", "import sys\nfor _ in range(200000): sys.stdout.write('x'*100)", "", time_limit_s=LIMIT)
    assert r.truncated and len(r.stdout) <= 64 * 1024 and case_verdict(r, "") == "OLE"
    assert await verdict("python", "x = bytearray(1024*1024*600)\nprint(len(x))") == "MLE"  # --memory 128m: OOM kill(137)


async def test_no_network_and_read_only_filesystem():
    net = "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), timeout=2)\n    print('CONNECTED')\nexcept OSError:\n    print('BLOCKED')\n"
    r = await SB.run("python", net, "", time_limit_s=LIMIT)
    assert r.stdout.strip() == "BLOCKED"
    fs = "try:\n    open('/work/evil.txt','w').write('x'); print('WROTE')\nexcept OSError:\n    print('DENIED')\ntry:\n    open('/etc/evil','w'); print('WROTE')\nexcept OSError:\n    print('DENIED')\n"
    r = await SB.run("python", fs, "", time_limit_s=LIMIT)
    assert r.stdout.split() == ["DENIED", "DENIED"]


async def test_fork_bomb_is_contained_and_runs_as_non_root():
    bomb = "import os\nfor _ in range(500):\n    try:\n        os.fork()\n    except OSError:\n        break\nprint('done')"
    r = await SB.run("python", bomb, "", time_limit_s=LIMIT)
    assert r.elapsed_ms < 8000  # pids-limit 로 폭주하지 않고 호스트 응답을 유지한다
    r = await SB.run("python", "import os;print(os.getuid())", "", time_limit_s=LIMIT)
    assert r.stdout.strip() == "10001"


async def test_no_container_left_behind():
    await SB.run("python", "while True: pass", "", time_limit_s=1.0)
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=judge-", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    assert out == []


@pytest.mark.skipif(not _has("sandbox-node:1"), reason="sandbox-node:1 이미지가 없음")
async def test_javascript():
    assert await verdict("javascript", "console.log(require('fs').readFileSync(0,'utf8').trim().split(' ').map(Number).reduce((a,b)=>a+b))", "1 2\n", "3") == "AC"
    assert await verdict("javascript", "undefinedFunction()") == "RE"


@pytest.mark.skipif(not _has("sandbox-java:1"), reason="sandbox-java:1 이미지가 없음")
async def test_java_compile_and_run():
    ok = "import java.util.*;public class Main{public static void main(String[] a){Scanner s=new Scanner(System.in);System.out.println(s.nextInt()+s.nextInt());}}"
    assert await verdict("java", ok, "1 2\n", "3") == "AC"
    r = await SB.run("java", "public class Main { oops }", "", time_limit_s=LIMIT)
    assert case_verdict(r, "") == "CE"
