// 화면 캡처·데모용 공고 채우기. 담당자 계정으로 REST API 를 호출해 공고를 만들고 게시한다 (개발 전용, 가짜 개인정보 없음).
//   import { fillDemoJobs } from "./demo-jobs.mjs";  await fillDemoJobs(request)  // request: Playwright APIRequestContext (baseURL 설정 필요)
// 이미 같은 제목의 공고가 있으면 건너뛴다. 실행 중인 개발 서버에 채우기: node scripts/capture/seed-demo-jobs.mjs http://localhost:8000

const COMMON = [
  "지원 동기와 이 직무에 관심을 갖게 된 계기를 말씀해 주세요",
  "팀에서 의견이 달랐을 때 조율한 경험을 말씀해 주세요",
  "최근에 새로 배운 것과 그것을 업무에 적용한 방법을 설명해 주세요",
  "마감이 촉박한 상황에서 우선순위를 정한 경험을 말씀해 주세요",
];
const BY_CATEGORY = {
  개발: [
    "가장 자신 있는 프로젝트에서 맡은 역할과 성과를 설명해 주세요",
    "성능 문제를 발견하고 개선했던 경험을 구체적으로 말씀해 주세요",
    "코드 리뷰에서 가장 많이 받은 피드백과 그 이후의 변화를 말씀해 주세요",
    "장애나 버그를 원인까지 추적해 해결한 경험을 설명해 주세요",
    "테스트 코드를 작성하며 느낀 장단점을 말씀해 주세요",
    "기술 선택에서 트레이드오프를 따져 결정한 사례를 설명해 주세요",
  ],
  디자인: [
    "가장 자신 있는 디자인 프로젝트와 그 안에서 맡은 역할을 설명해 주세요",
    "사용자 피드백을 디자인에 반영한 경험을 말씀해 주세요",
    "개발자와 협업하며 디자인을 조정했던 사례를 설명해 주세요",
    "디자인 시스템을 만들거나 개선한 경험이 있다면 말씀해 주세요",
    "결과물을 어떤 기준으로 평가하는지 설명해 주세요",
    "이해관계자를 설득해 디자인 방향을 정한 경험을 말씀해 주세요",
  ],
  기획: [
    "가장 자신 있는 기획 프로젝트와 그 안에서 맡은 역할을 설명해 주세요",
    "문제를 정의하고 지표로 성과를 확인한 경험을 말씀해 주세요",
    "요구사항이 자주 바뀌는 상황에서 일정을 관리한 경험을 설명해 주세요",
    "데이터를 근거로 의사결정을 바꾼 사례를 말씀해 주세요",
    "개발·디자인 팀과 우선순위를 맞춘 방법을 설명해 주세요",
    "출시 후 기대와 다른 결과가 나왔을 때 대응한 경험을 말씀해 주세요",
  ],
  마케팅: [
    "가장 자신 있는 캠페인과 그 안에서 맡은 역할을 설명해 주세요",
    "채널별 성과를 비교해 예산을 조정한 경험을 말씀해 주세요",
    "실험을 설계하고 결과를 해석한 사례를 설명해 주세요",
    "타깃 고객을 정의하고 메시지를 정한 과정을 말씀해 주세요",
    "성과가 기대에 못 미쳤을 때 원인을 찾은 경험을 설명해 주세요",
    "콘텐츠 기획에서 가장 중요하게 보는 기준을 말씀해 주세요",
  ],
  영업: [
    "가장 자신 있는 영업 사례와 그 안에서 맡은 역할을 설명해 주세요",
    "고객의 거절을 극복하고 계약으로 이어간 경험을 말씀해 주세요",
    "고객의 숨은 요구를 파악해 제안한 사례를 설명해 주세요",
    "장기 거래처와 관계를 유지하는 방법을 말씀해 주세요",
    "목표 달성이 어려웠던 분기에 어떻게 대응했는지 설명해 주세요",
    "내부 팀과 협업해 고객 문제를 해결한 경험을 말씀해 주세요",
  ],
};

const JOBS = [
  { title: "프론트엔드 개발자 (React)", cat: "개발", days: 2, n: 3, loc: "서울 성동구", type: "regular", duties: "- 사용자 화면 설계와 구현\n- 디자인 시스템 컴포넌트 개선\n- 성능 측정과 렌더링 최적화", req: "- React, TypeScript 기반 개발 경험\n- 웹 접근성과 반응형 구현 이해\n- Git 으로 협업해 본 경험" },
  { title: "데이터 엔지니어", cat: "개발", days: 9, n: 2, loc: "서울 성동구", type: "regular", duties: "- 배치·스트리밍 데이터 파이프라인 구축\n- 데이터 품질 점검과 모니터링\n- 분석 팀을 위한 데이터 마트 설계", req: "- SQL 과 Python 활용 경험\n- 데이터 웨어하우스 설계 이해\n- 워크플로 도구 사용 경험" },
  { title: "QA 엔지니어", cat: "개발", days: 20, n: 1, loc: "서울 성동구", type: "contract", duties: "- 릴리스 전 회귀 테스트 설계\n- 자동화 테스트 작성과 유지\n- 결함 분석과 재현 절차 정리", req: "- 테스트 케이스 설계 경험\n- 자동화 도구(Playwright 등) 사용 경험" },
  { title: "프로덕트 디자이너", cat: "디자인", days: 6, n: 1, loc: "서울 성동구", type: "regular", duties: "- 커머스 앱 화면 설계\n- 사용성 테스트와 개선안 도출\n- 디자인 시스템 운영", req: "- Figma 기반 UI 설계 경험\n- 포트폴리오 제출 가능" },
  { title: "UX 리서처", cat: "디자인", days: 8, n: 1, loc: "서울 성동구", type: "regular", duties: "- 사용자 인터뷰와 설문 설계\n- 조사 결과 정리와 공유\n- 제품 팀과 개선 과제 도출", req: "- 정성·정량 조사 경험\n- 조사 결과를 문서로 정리한 경험" },
  { title: "서비스 기획자", cat: "기획", days: 12, n: 2, loc: "서울 성동구", type: "regular", duties: "- 신규 기능 기획과 요구사항 정의\n- 지표 설계와 성과 분석\n- 개발·디자인 팀과 일정 조율", req: "- 서비스 기획 또는 PM 경험\n- 데이터 기반 의사결정 경험" },
  { title: "그로스 마케터", cat: "마케팅", days: 4, n: 2, loc: "서울 성동구", type: "regular", duties: "- 퍼포먼스 광고 운영과 성과 분석\n- 전환 실험 설계\n- CRM 메시지 기획", req: "- 광고 매체 운영 경험\n- 스프레드시트·SQL 로 성과를 분석한 경험" },
  { title: "B2B 영업 담당자", cat: "영업", days: 15, n: 3, loc: "서울 성동구", type: "regular", duties: "- 신규 거래처 발굴과 제안\n- 계약 협의와 사후 관리\n- 영업 현황 보고", req: "- B2B 영업 또는 제안 경험\n- 고객 응대와 문서 작성 능력" },
];

export async function fillDemoJobs(request, { email = "hr@corp.local", password = "Passw0rd!" } = {}) {
  const ok = async (res, what) => { if (!res.ok()) throw new Error(`${what} 실패: ${res.status()} ${await res.text()}`); return res.json(); };
  await ok(await request.post("/api/v1/auth/login", { data: { email, password, role: "recruiter" } }), "로그인");
  const existing = new Set((await ok(await request.get("/api/v1/admin/jobs"), "공고 조회")).items?.map((j) => j.title) ?? []);
  let made = 0;
  for (const j of JOBS) {
    if (existing.has(j.title)) continue;
    const created = await ok(await request.post("/api/v1/admin/jobs", { data: {
      title: j.title, job_category: j.cat, headcount: j.n, deadline_at: new Date(Date.now() + j.days * 86_400_000).toISOString(),
      duties: j.duties, requirements: j.req, contact_email: email, work_location: j.loc, employment_type: j.type, answer_time_limit_sec: 60,
    } }), `${j.title} 생성`);
    const qs = [...BY_CATEGORY[j.cat], ...COMMON].slice(0, 10);
    await ok(await request.put(`/api/v1/admin/jobs/${created.id}/questions`, { data: { items: qs.map((text) => ({ text })) } }), `${j.title} 질문`);
    await ok(await request.post(`/api/v1/admin/jobs/${created.id}/publish`), `${j.title} 게시`);
    made++;
  }
  return made;
}
