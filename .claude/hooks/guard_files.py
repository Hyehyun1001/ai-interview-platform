#!/usr/bin/env python3
"""PreToolUse hook: 비밀·개인정보 파일 수정을 차단한다 (NFR-S1/S2)."""
import json, sys

try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
path = (data.get("tool_input") or {}).get("file_path", "")
name = path.rsplit("/", 1)[-1]

blocked = name == ".env" or name.startswith(".env.") and name != ".env.example"
blocked = blocked or name.endswith((".pem", ".key"))
blocked = blocked or "/data/" in path and path.endswith((".wav", ".webm", ".mp4", ".pdf"))
if blocked:
    print(f"차단: {path} 는 비밀/개인정보 파일입니다. 직접 수정하지 마세요.", file=sys.stderr)
    sys.exit(2)  # exit 2 = 도구 호출 거부, stderr 가 Claude 에게 전달됨
