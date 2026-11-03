---
name: bench
description: 지연·메모리 벤치마크를 재측정한다. 수치를 문서나 답변에 쓰기 전에 사용.
---
규칙: 측정 없이 지연·메모리 수치를 말하지 않는다.

1. `ollama serve` 가 떠 있는지 확인한다.
2. 모델 없이 점검: `backend/.venv/bin/python backend/tests/benchmark_ai.py --selftest`
3. 전체 측정: `backend/.venv/bin/python backend/tests/benchmark_ai.py` (옵션은 스크립트 docstring 참고)
4. 결과는 `data/benchmarks/` 에 저장된다(gitignore). p50/p95 를 표로 요약하고, 목표(p50 ≤ 9.5s, p95 ≤ 12s) 대비 판정을 쓴다.
5. 측정 횟수가 100회 미만이면 "비공식 측정"이라고 명시한다.
