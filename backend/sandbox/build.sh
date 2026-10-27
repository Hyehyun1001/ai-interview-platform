#!/usr/bin/env bash
# 코딩테스트 샌드박스 이미지를 사전 빌드한다 (TRD §5.2). 런타임에는 pull 하지 않는다 — 빌드 때만 네트워크 필요.
#   ./build.sh [python|node|java ...]   (인자 없으면 전부)
set -euo pipefail
cd "$(dirname "$0")"
targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=(python node java)
for t in "${targets[@]}"; do
  docker build -f "$t.Dockerfile" -t "sandbox-$([ "$t" = node ] && echo node || echo "$t"):1" .
done
