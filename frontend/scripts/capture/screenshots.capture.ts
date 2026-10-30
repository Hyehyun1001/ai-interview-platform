import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { login } from "../../e2e/helpers";

/** README 화면 캡처(docs/assets/screenshots). 시드된 데모 데이터만 쓰며 실제 개인정보는 없다. */
const OUT = path.join(__dirname, "../../../docs/assets/screenshots");
const PDF = path.join(__dirname, "../../e2e/fixtures/resume-ko.pdf");
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

test.describe.configure({ mode: "serial" });

test("지원자 화면 4장: APP-03/05/06/07", async ({ browser }) => {
  const ctx = await browser.newContext({ permissions: ["camera", "microphone"], viewport: { width: 1440, height: 900 }, locale: "ko-KR" });
  const page = await ctx.newPage();
  const email = `capture-${Date.now()}@corp.local`;
  expect((await page.request.post("/api/v1/auth/register", { data: { name: "김지원", email, password: "Passw0rd!", password_confirm: "Passw0rd!", birth_date: "1999-03-02", gender: "female", phone: "010-0000-0000" } })).status()).toBe(201);
  // 가입하면 이미 로그인된 상태다

  // APP-03 공고 상세 + 보안 동의 모달
  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" }).click();
  await expect(page.getByText("내부망 서버에서만 처리")).toBeVisible();
  await page.getByTestId("apply-btn").click();
  const dialog = page.getByRole("dialog", { name: "개인정보 활용 동의" });
  await dialog.getByLabel(/개인정보 수집·이용에 동의/).check();
  await dialog.getByLabel(/녹화·저장 및 AI 평가에 동의/).check();
  await expect(dialog.getByRole("button", { name: "동의하고 계속" })).toBeEnabled();
  await page.mouse.move(5, 450);
  await page.waitForTimeout(600);
  await shot(page, "app-03-job-detail");
  await dialog.getByRole("button", { name: "동의하고 계속" }).click();

  // APP-05 이력서 PDF 업로드·분석. 가짜 엔진은 추출 결과가 비어 있으므로, 추출이 성공했을 때의 화면을 찍기 위해 조회 응답만 데모 이력서로 대체한다.
  await page.route("**/api/v1/resume-jobs/*", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    status: "done", used_ocr: false, dropped: 0, fell_back: false, error_code: null, error_message: null,
    data: {
      name: "김지원",
      education: [{ school: "한빛대학교", major: "컴퓨터공학", degree: "학사", start: "2019.03", end: "2023.02" }],
      experience: [{ company: "다온커머스", role: "백엔드 인턴", start: "2022.07", end: "2022.12", summary: "주문 API 성능 개선, Redis 캐시 도입" }],
      projects: [{ title: "주문·결제 API 리팩터링", role: "백엔드", period: "2022.09 ~ 2022.11", tech_stack: ["Java", "Spring", "Redis"], description: "조회 성능 개선을 위해 캐시 계층 설계, p95 응답 시간 단축" }],
      skills: ["Java", "Spring", "MySQL", "Redis"], certifications: ["정보처리기사"],
    } }) }));
  await page.getByTestId("pdf-input").setInputFiles(PDF);
  await expect(page.getByTestId("extracted-banner")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("성명")).toHaveValue("김지원");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await shot(page, "app-05-resume");
  await page.getByTestId("next-btn").click();
  await page.unroute("**/api/v1/resume-jobs/*");

  // APP-06 사전 환경 점검
  await expect(page).toHaveURL(/\/device-check$/);
  const status = (s: string) => page.getByTestId(`step-${s}`);
  await expect(status("camera")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });
  await expect(status("mic")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });
  await page.getByTestId("play-guide").click();
  await page.getByTestId("heard-yes").click();
  await expect(page.getByTestId("start-interview")).toBeEnabled({ timeout: 10_000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "app-06-device-check");

  // APP-07 실시간 면접
  await page.getByTestId("start-interview").click();
  await expect(page).toHaveURL(/\/interview\/[0-9a-f-]+$/, { timeout: 60_000 });
  await page.getByTestId("start-btn").click();
  await expect(page.getByTestId("caption")).toContainText(/\S/, { timeout: 20_000 });
  const countdown = page.getByText("잠시 후 답변을 시작해 주세요");
  await expect(countdown).toBeVisible({ timeout: 20_000 });
  await expect(countdown).toBeHidden({ timeout: 30_000 });   // 시작 카운트다운이 끝난 뒤
  await page.waitForTimeout(2500);
  await shot(page, "app-07-interview");
  await ctx.close();
});

test("관리자 화면 4장: ADM-01/03/05/06", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ko-KR" });
  const page = await ctx.newPage();
  await login(page, "hr@corp.local", "recruiter");
  await expect(page).toHaveURL(/\/admin/);

  // ADM-01 대시보드
  await expect(page.getByText("다가오는 면접")).toBeVisible();
  await expect(page.getByText("백엔드 개발자 (신입)").first()).toBeVisible();
  await page.mouse.move(1000, 20);                                  // 차트 툴팁이 뜨지 않게
  await page.waitForTimeout(800);
  await shot(page, "adm-01-dashboard");

  // ADM-05 비교
  await page.getByLabel("이도윤 비교 선택").check();
  await page.getByLabel("최서연 비교 선택").check();
  await page.getByRole("link", { name: "선택한 지원자 비교하기" }).click();
  await expect(page).toHaveURL(/compare/);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200);                                  // 차트 애니메이션
  await shot(page, "adm-05-compare");

  // ADM-06 상세 + 하이라이트 플레이어
  await page.goto("/admin");
  await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
  await page.getByRole("tab", { name: "문답·플레이어" }).click();
  await expect(page.getByTestId("highlight-player")).toBeVisible();
  await expect(page.getByTestId("segment-list").getByText("감점").first()).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "adm-06-player");

  // ADM-03 공고 작성 마법사(2단계: 질문 세트·AI 질문 뱅크)
  const j = await (await page.request.post("/api/v1/admin/jobs", { data: { title: "플랫폼 백엔드 엔지니어", job_category: "개발", headcount: 2, deadline_at: new Date(Date.now() + 14 * 86400_000).toISOString(), duties: "- 결제 API 설계와 성능 개선\n- 장애 대응과 모니터링", requirements: "- Java/Spring 경험\n- RDBMS 설계 경험", preferred: "- 대용량 트래픽 경험" } })).json();
  const qs = ["최근 진행한 프로젝트에서 맡은 역할과 성과를 설명해 주세요", "트랜잭션 격리 수준을 선택한 경험을 말씀해 주세요", "장애를 해결했던 경험을 설명해 주세요", "Redis 캐시 무효화 전략을 어떻게 설계하시겠어요?"];
  expect((await page.request.put(`/api/v1/admin/jobs/${j.id}/questions`, { data: { items: qs.map((text) => ({ text })) } })).ok()).toBe(true);
  await page.goto(`/admin/jobs/${j.id}/edit?step=2`);
  await expect(page.getByLabel("질문 1", { exact: true })).toHaveValue(qs[0]!);
  await page.waitForTimeout(800);
  await shot(page, "adm-03-wizard");
  await ctx.close();
});
