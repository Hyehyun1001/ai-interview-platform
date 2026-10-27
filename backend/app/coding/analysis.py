"""정적 분석 (COD-4, TRD §5.5). Python 은 분석 컨테이너의 ruff + radon, Java/JS 는 소스 텍스트만 읽는 경량 지표(코드를 실행하지 않는다).

결과는 `code_submissions.static_analysis`(JSON)에 저장되고 코드 꼬리질문·code_quality 점수의 근거가 된다. 소스 원문은 담지 않는다.
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any


def _text_metrics(source: str, func_re: re.Pattern[str]) -> dict[str, Any]:
    lines = [ln for ln in source.splitlines() if ln.strip()]
    depth = max_depth = 0
    for ch in source:
        if ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)
    return {"lines": len(lines), "functions": len(func_re.findall(source)), "max_nesting": max_depth,
            "todo_markers": len(re.findall(r"TODO|FIXME", source)), "long_lines": sum(1 for ln in source.splitlines() if len(ln) > 120)}


def _python_ast_metrics(source: str) -> dict[str, Any]:
    out: dict[str, Any] = {"lines": len([ln for ln in source.splitlines() if ln.strip()]), "long_lines": sum(1 for ln in source.splitlines() if len(ln) > 120),
                           "todo_markers": len(re.findall(r"TODO|FIXME", source))}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out | {"syntax_error": True}
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    branch = (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.ExceptHandler, ast.comprehension)
    out["functions"] = len(funcs)
    out["max_function_len"] = max((n.end_lineno - n.lineno + 1 for n in funcs if n.end_lineno), default=0)
    out["max_complexity"] = 1 + max((sum(isinstance(c, branch) for c in ast.walk(n)) for n in funcs), default=sum(isinstance(c, branch) for c in ast.walk(tree)))
    return out


def parse_python_tools(raw: str) -> dict[str, Any] | None:
    """`ruff json @@ radon cc json @@ radon mi json` 출력 파싱. 형식이 어긋나면 None."""
    try:
        ruff_s, cc_s, mi_s = (x.strip() for x in raw.split("@@"))
        ruff = json.loads(ruff_s or "[]")
        cc = json.loads(cc_s or "{}")
        mi = json.loads(mi_s or "{}")
    except (ValueError, TypeError):
        return None
    blocks = [b for v in cc.values() if isinstance(v, list) for b in v if isinstance(b, dict)]
    mi_vals = [v.get("mi") for v in mi.values() if isinstance(v, dict) and isinstance(v.get("mi"), (int, float))]
    return {"lint_issues": len(ruff) if isinstance(ruff, list) else 0,
            "lint_codes": sorted({str(i.get("code")) for i in ruff if isinstance(i, dict) and i.get("code")})[:10] if isinstance(ruff, list) else [],
            "max_complexity": max((int(b.get("complexity", 0)) for b in blocks), default=0),
            "maintainability": round(min(mi_vals), 1) if mi_vals else None}


async def analyze_source(sandbox: Any, language: str, source: str) -> dict[str, Any]:
    if language == "python":
        base = _python_ast_metrics(source)
        tools = None
        if hasattr(sandbox, "analyze_python_in_container"):
            try:
                raw = await sandbox.analyze_python_in_container(source)
                tools = parse_python_tools(raw["raw"]) if raw else None
            except Exception:  # noqa: BLE001  분석 실패는 채점을 막지 않는다
                tools = None
        return base | (tools or {}) | {"tool": "ruff+radon" if tools else "ast"}
    if language == "java":
        return _text_metrics(source, re.compile(r"\b(?:public|private|protected|static)[\w<>\[\], ]*\s+\w+\s*\([^)]*\)\s*(?:throws [\w, .]+)?\s*\{")) | {"tool": "text"}
    return _text_metrics(source, re.compile(r"\bfunction\b|=>")) | {"tool": "text"}


def quality_score(verdict: str | None, case_results: list[dict] | None, analysis: dict[str, Any] | None) -> float:
    """code_quality 점수(0~100). 정답률 70% + 정적 분석 30% — LLM 을 쓰지 않는 결정적 계산이다."""
    cases = case_results or []
    passed = sum(1 for c in cases if c.get("verdict") == "AC")
    correctness = 100.0 * passed / len(cases) if cases else 0.0
    if verdict == "CE":
        correctness = 0.0
    a = analysis or {}
    style = 100.0
    style -= min(40, 5 * int(a.get("lint_issues", 0) or 0))
    style -= max(0, min(30, (int(a.get("max_complexity", 0) or 0) - 10) * 3))
    style -= max(0, min(20, (int(a.get("max_function_len", 0) or 0) - 50) // 2))
    style -= min(10, 2 * int(a.get("long_lines", 0) or 0))
    return round(max(0.0, min(100.0, 0.7 * correctness + 0.3 * max(0.0, style))), 2)
