import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.describe.configure({ mode: "serial" });

test("ADM-03 공고 작성 마법사: 4단계 → 게시 → 지원자에게 노출", async ({ page, browser }) => {
  await login(page, "hr@corp.local", "recruiter");
  await page.goto("/admin/jobs/new");

  // ① 기본 정보 — 제목 없이는 저장 불가
  await page.getByRole("button", { name: /저장하고 다음/ }).click();
  await expect(page.getByText("공고 제목을 입력해 주세요")).toBeVisible();
  await page.getByLabel("공고 제목 *").fill("플랫폼 개발자 (E2E)");
  await page.getByLabel("직무 카테고리 *").selectOption("개발");
  await page.getByLabel("모집 정원 *").fill("2");
  const d = new Date(Date.now() + 7 * 86_400_000);
  await page.getByLabel("마감일 *").fill(new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16));
  await page.getByLabel("주요 업무 *").fill("결제 API 설계와 성능 개선");
  await page.getByLabel("지원 요건 *").fill("Java, Redis 경험");
  await page.getByRole("button", { name: /저장하고 다음/ }).click();
  await expect(page).toHaveURL(/\/edit\?step=2/);

  // ② 질문 — 금칙어 경고, AI 뱅크는 가짜 LLM 이라 실패 안내
  await page.getByLabel("질문 1", { exact: true }).fill("결혼 계획이 있으신가요?");
  await expect(page.getByText("채용 공정성 정책에 따라 사용할 수 없는 질문입니다")).toBeVisible();
  await page.getByRole("button", { name: /저장하고 다음/ }).click();
  await expect(page.getByText("사용할 수 없는 질문이 있어요")).toBeVisible();  // 저장 차단
  await page.getByRole("button", { name: /JD 기반 질문 추출/ }).click();
  await expect(page.getByTestId("bank-status")).toContainText(/실패|짧거나/, { timeout: 20_000 });
  for (let i = 1; i <= 10; i++) await page.getByLabel(`질문 ${i}`, { exact: true }).fill(`${i}번째 직접 질문입니다. 경험을 설명해 주세요`);
  await page.getByRole("button", { name: /저장하고 다음/ }).click();

  // ③ 가중치 — 합계 ≠ 100 이면 진행 불가
  await expect(page.getByTestId("weights-sum")).toContainText("100");
  await page.getByLabel("논리성 가중치").fill("30");
  await expect(page.getByTestId("weights-sum")).toContainText("초과");  // 초과 안내
  await expect(page.getByRole("button", { name: /저장하고 다음/ })).toBeDisabled();
  await page.getByRole("button", { name: "기본값으로" }).click();
  await expect(page.getByTestId("weights-sum")).toContainText("✔");
  await page.getByLabel("합격선(cutoff) 0~100").fill("70");
  await expect(page.getByTestId("cutoff-preview")).toContainText("75점 이상");
  await page.getByRole("button", { name: /저장하고 다음/ }).click();

  // ④ 검토 — 체크리스트 후 게시
  await expect(page.getByTestId("checklist")).toContainText("질문 풀 충분 (직접 10");
  await page.getByTestId("publish-btn").click();
  await expect(page).toHaveURL(/\/admin\/jobs$/);
  await expect(page.getByText("플랫폼 개발자 (E2E)")).toBeVisible();

  const ctx = await browser.newContext();
  const ap = await ctx.newPage();
  await login(ap, "applicant@corp.local", "applicant");
  const jobs = await (await ap.request.get("/api/v1/jobs")).json();
  expect(jobs.items.map((j: { title: string }) => j.title)).toContain("플랫폼 개발자 (E2E)");
  await ctx.close();
});

test("ADM-05 비교: 대시보드에서 2명 선택 → 레이더/표/최고점 강조", async ({ page }) => {
  await login(page, "hr@corp.local", "recruiter");
  await page.getByLabel("이도윤 비교 선택").check();
  await page.getByLabel("최서연 비교 선택").check();
  await page.getByRole("link", { name: "선택한 지원자 비교하기" }).click();
  await expect(page).toHaveURL(/compare\?ids=/);
  const table = page.getByTestId("compare-table");
  await expect(table).toContainText("이도윤");
  await expect(table).toContainText("최서연");
  await expect(table.getByRole("row", { name: /AI 종합 점수/ })).toContainText("82.5");
  await expect(table.getByLabel("최고점").first()).toBeVisible();
  await expect(page.getByRole("img", { name: /항목별 점수 비교/ })).toBeVisible();
  // 범례 토글
  const legend = page.getByRole("button", { name: /이도윤/ }).first();
  await legend.click();
  await expect(legend).toHaveAttribute("aria-pressed", "false");
  // 잘못된 ids → 대시보드로
  await page.goto("/admin/applicants/compare?ids=only-one");
  await expect(page).toHaveURL(/\/admin$/);
});

test("ADM-06 결정·메일: 합격 처리 → 메일 → 안내 후 변경은 확인 필요", async ({ page }) => {
  await login(page, "hr@corp.local", "recruiter");
  await page.getByRole("row", { name: /최서연/ }).getByRole("link", { name: "상세 보기" }).click();
  const badge = page.getByTestId("decision-badge");
  await expect(badge).toHaveText("결정 대기");
  // 결정 전에는 두 버튼이 똑같이 중립 색이고, 눌러서 확정한 쪽만 파란색(선택됨)이 된다
  const pass = page.getByTestId("decision-pass"), fail = page.getByTestId("decision-fail");
  for (const b of [pass, fail]) { await expect(b).toHaveAttribute("aria-pressed", "false"); await expect(b).not.toHaveClass(/bg-primary/); }
  await page.getByRole("button", { name: "합격 처리", exact: true }).click();
  await page.getByTestId("decision-confirm").click();
  await expect(badge).toHaveText("합격");
  await expect(pass).toHaveAttribute("aria-pressed", "true"); await expect(pass).toHaveClass(/bg-primary/);
  await expect(fail).toHaveAttribute("aria-pressed", "false"); await expect(fail).not.toHaveClass(/bg-primary/);

  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "안내 메일" }).click();
  await page.getByTestId("mail-send").click();
  await expect(page.getByText("안내 메일을 보냈어요")).toBeVisible();

  await page.getByRole("button", { name: "불합격 처리" }).click();
  await page.getByTestId("decision-confirm").click();  // 안내 메일 발송됨 → 409 → 확인 모달
  await expect(page.getByRole("button", { name: "변경 확인" })).toBeVisible();
  await page.getByRole("button", { name: "변경 확인" }).click();
  await expect(badge).toHaveText("불합격");
  await expect(fail).toHaveClass(/bg-primary/); await expect(pass).not.toHaveClass(/bg-primary/);
  await page.getByRole("button", { name: "결정 취소" }).click();
  await page.getByTestId("decision-confirm").click();  // 안내 메일이 나간 건이라 취소도 확인 필요
  await page.getByRole("button", { name: "변경 확인" }).click();
  await expect(badge).toHaveText("결정 대기");
  for (const b of [pass, fail]) await expect(b).not.toHaveClass(/bg-primary/);   // 취소하면 다시 둘 다 중립
});

test("열람 확인: 상세에 2초 머물면 미검토 KPI 가 줄어든다", async ({ page }) => {
  await login(page, "hr@corp.local", "recruiter");
  const before = (await (await page.request.get("/api/v1/admin/dashboard")).json()).summary.unreviewed_applicants;
  await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
  await expect(page.getByTestId("decision-panel")).toBeVisible();
  await expect.poll(async () => (await (await page.request.get("/api/v1/admin/dashboard")).json()).summary.unreviewed_applicants, { timeout: 8000 }).toBeLessThan(before);
});

test("APP-09 지원자 리포트: 점수·강점·시선, AI 예상 합불은 없다", async ({ page }) => {
  await login(page, "demo0@corp.local", "applicant");
  const mine = await (await page.request.get("/api/v1/me/applications")).json();
  const sid = mine[0].session_id as string;
  await page.goto(`/reports/${sid}`);
  await expect(page.getByTestId("total-score")).toHaveText("82.5");
  await expect(page.getByText("정량적 성과 제시")).toBeVisible();
  await expect(page.getByText(/시선 이탈 비율/)).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/합격권|likely_pass|예상 합불/);
  // 리포트 생성 중인 지원자는 대기 화면으로
  const ctx = await page.context().browser()!.newContext();
  const p2 = await ctx.newPage();
  await login(p2, "demo2@corp.local", "applicant");
  const sid2 = (await (await p2.request.get("/api/v1/me/applications")).json())[0].session_id as string;
  await p2.goto(`/reports/${sid2}`);
  await expect(p2).toHaveURL(new RegExp(`/interview/${sid2}/waiting`));
  await expect(p2.getByTestId("waiting")).toBeVisible();
  await ctx.close();
});
