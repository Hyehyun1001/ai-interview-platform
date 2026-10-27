"""내장 문제 은행. TRD 에 문제 저장 스키마가 없어(공고 마법사에도 문제 작성 화면이 없다) 코드에 둔다 — 세션마다 결정적으로 1문제를 고른다.

모든 문제는 표준 입출력(stdin → stdout)이며 채점은 줄 끝 공백을 무시하고 비교한다. 케이스는 최대 10개(TRD §5.3), 앞의 `samples` 개만 지원자에게 공개된다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

LANGUAGES: dict[str, dict[str, str]] = {
    "python": {"label": "Python 3.11", "file": "main.py", "image": "sandbox-python:1"},
    "java": {"label": "Java 17", "file": "Main.java", "image": "sandbox-java:1"},
    "javascript": {"label": "JavaScript (Node 20)", "file": "main.js", "image": "sandbox-node:1"},
}

STARTERS = {
    "python": "import sys\n\n\ndef main():\n    data = sys.stdin.read().split()\n    # TODO: 풀이를 작성하세요\n    print()\n\n\nmain()\n",
    "java": "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n"
            "        // TODO: 풀이를 작성하세요\n        System.out.println();\n    }\n}\n",
    "javascript": "const data = require('fs').readFileSync(0, 'utf8').split(/\\s+/).filter(Boolean);\n// TODO: 풀이를 작성하세요\nconsole.log();\n",
}


@dataclass(frozen=True)
class Case:
    stdin: str
    expected: str


@dataclass(frozen=True)
class Problem:
    id: str
    title: str
    statement: str
    input_format: str
    output_format: str
    constraints: list[str]
    cases: list[Case]
    samples: int = 2
    examples: list[Case] = field(default_factory=list)  # 지원자에게 보여 줄 예시(= 앞의 samples 개 케이스)


def _p(id_: str, title: str, statement: str, inp: str, out: str, constraints: list[str], cases: list[tuple[str, str]], samples: int = 2) -> Problem:
    cs = [Case(i, o) for i, o in cases]
    assert 2 <= len(cs) <= 10 and samples <= len(cs)
    return Problem(id_, title, statement, inp, out, constraints, cs, samples, cs[:samples])


PROBLEMS: list[Problem] = [
    _p("two-sum", "두 수의 합",
       "정수 배열과 목표 값 target 이 주어집니다. 합이 target 이 되는 서로 다른 두 원소의 인덱스(0부터 시작) i, j (i < j)를 찾으세요. 정답은 항상 정확히 하나 존재합니다.",
       "첫 줄에 n 과 target, 둘째 줄에 n 개의 정수가 공백으로 구분되어 주어집니다.", "i 와 j 를 공백으로 구분해 한 줄에 출력합니다.",
       ["2 ≤ n ≤ 10,000", "-10^9 ≤ 원소, target ≤ 10^9", "정답은 유일합니다"],
       [("4 9\n2 7 11 15\n", "0 1"), ("3 6\n3 2 4\n", "1 2"), ("2 -3\n-1 -2\n", "0 1"), ("5 0\n5 -5 1 2 3\n", "0 1"),
        ("6 17\n1 3 5 7 9 8\n", "4 5"), ("5 100\n10 20 30 40 60\n", "3 4")]),
    _p("brackets", "올바른 괄호",
       "소괄호 ( ), 중괄호 { }, 대괄호 [ ] 로만 이루어진 문자열이 올바른 괄호열인지 판별하세요.",
       "한 줄에 문자열 s 가 주어집니다.", "올바르면 YES, 아니면 NO 를 출력합니다.",
       ["1 ≤ |s| ≤ 100,000"],
       [("()[]{}\n", "YES"), ("(]\n", "NO"), ("{[()]}\n", "YES"), ("(((\n", "NO"), (")(\n", "NO"), ("([{}])([])\n", "YES"), ("]\n", "NO")]),
    _p("top-word", "가장 많이 나온 단어",
       "공백으로 구분된 단어들이 주어집니다. 가장 많이 등장한 단어와 그 횟수를 구하세요. 횟수가 같으면 사전순으로 앞서는 단어를 선택합니다.",
       "첫 줄에 단어 개수 n, 둘째 줄에 n 개의 단어가 공백으로 구분되어 주어집니다.", "단어와 횟수를 공백으로 구분해 한 줄에 출력합니다.",
       ["1 ≤ n ≤ 100,000", "단어는 영문 소문자 1~20자"],
       [("5\napple banana apple cherry banana\n", "apple 2"), ("3\nzed alpha zed\n", "zed 2"), ("1\nsolo\n", "solo 1"),
        ("4\nb a b a\n", "a 2"), ("6\nx y z x y z\n", "x 2")]),
]


def pick_problem(session_id: uuid.UUID) -> Problem:
    return PROBLEMS[session_id.int % len(PROBLEMS)]


def get_problem(problem_id: str) -> Problem | None:
    return next((p for p in PROBLEMS if p.id == problem_id), None)
