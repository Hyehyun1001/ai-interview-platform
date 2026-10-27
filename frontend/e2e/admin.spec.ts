import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.beforeEach(async ({ page }) => {
  await login(page, "hr@corp.local", "recruiter");
  await expect(page).toHaveURL(/\/admin/);
});

test("대시보드: 실제 API 의 KPI·공고 카드·지원자 표, 비교 선택 규칙", async ({ page }) => {
  await expect(page.getByText("다가오는 면접")).toBeVisible();
  await expect(page.getByText("백엔드 개발자 (신입)").first()).toBeVisible();
  await expect(page.getByText("코테 OFF").first()).toBeVisible();
  

  // 리포트 생성 중인 지원자는 비교 선택 불가
  await expect(page.getByLabel("정하늘 비교 선택")).toBeDisabled();
  // 같은 공고의 리포트 완료 2명 선택 → 비교 버튼 활성
  await page.getByLabel("이도윤 비교 선택").check();
  await expect(page.getByRole("link", { name: "선택한 지원자 비교하기" })).toHaveAttribute("aria-disabled", "true");
  await page.getByLabel("최서연 비교 선택").check();
  await expect(page.getByRole("link", { name: "선택한 지원자 비교하기" })).not.toHaveAttribute("aria-disabled", "true");
});

test("지원자 상세: 하이라이트 구간 재생 + 단축키 (프록시를 거친 Range 오디오)", async ({ page }) => {
  await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
  await expect(page.getByTestId("highlight-player")).toBeVisible();
  await expect(page.getByTestId("segment-list").getByText("감점").first()).toBeVisible();

  const time = page.getByTestId("player-time");
  await page.getByRole("button", { name: /이 구간 듣기/ }).first().click();
  await expect.poll(async () => (await time.textContent()) ?? "", { timeout: 10_000 }).not.toMatch(/^0:00 /);
  await page.getByTestId("play-toggle").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("timeline-track")).toHaveAttribute("aria-valuenow", /\d+/);
});

test("면접 일정 추가가 서버에 저장되고 KPI 에 반영된다", async ({ page }) => {
  await page.getByRole("button", { name: "면접 일정 추가" }).click();
  await page.getByLabel("제목").fill("1차 면접 - 김지원");
  const start = new Date(Date.now() + 3 * 3600_000);
  const local = new Date(start.getTime() - start.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  await page.getByLabel("시작").fill(local);
  await page.getByRole("button", { name: "추가", exact: true }).click();
  await expect(page.getByText("면접 일정을 추가했어요")).toBeVisible();
  const dash = await (await page.request.get("/api/v1/admin/dashboard")).json();
  expect(dash.summary.upcoming_interviews.total).toBeGreaterThanOrEqual(1);
});

test("권한: 지원자 계정은 관리자 API 를 쓸 수 없다", async ({ browser }) => {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await login(p, "applicant@corp.local", "applicant");
  await expect(p).toHaveURL(/\/jobs/);
  expect((await p.request.get("/api/v1/admin/dashboard")).status()).toBe(403);
  await ctx.close();
});
