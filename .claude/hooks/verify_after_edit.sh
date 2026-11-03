#!/usr/bin/env bash
# PostToolUse hook: 수정한 파일을 가볍게 검증한다. 실패하면 exit 2 로 Claude 에게 되돌린다.
# 전체 테스트 스위트는 매 수정마다 돌리지 않는다 (작업 완료 시 에이전트/사용자가 실행).
f=$(python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null)
root="${CLAUDE_PROJECT_DIR:-.}"
case "$f" in
  */backend/tests/test_*.py)
    # 수정한 테스트 파일만 실행
    [ -x "$root/backend/.venv/bin/python" ] || exit 0
    out=$(cd "$root/backend" && .venv/bin/python -m pytest -x -q "$f" 2>&1) || { echo "$out" | tail -25 >&2; exit 2; } ;;
  */backend/*.py)
    # 문법 오류만 빠르게 확인
    [ -x "$root/backend/.venv/bin/python" ] || exit 0
    out=$("$root/backend/.venv/bin/python" -m py_compile "$f" 2>&1) || { echo "$out" | tail -25 >&2; exit 2; } ;;
  */frontend/*.ts|*/frontend/*.tsx)
    [ -d "$root/frontend/node_modules" ] || exit 0
    out=$(cd "$root/frontend" && npm run typecheck 2>&1) || { echo "$out" | tail -25 >&2; exit 2; } ;;
esac
exit 0
