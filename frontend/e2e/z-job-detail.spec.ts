import { expect, test } from "@playwright/test";
import { login } from "./helpers";

/** 공고 목록·상세(APP-02/03)와 담당자 미리보기가 같은 상세 구성(요약·채용 절차·안내)을 보여 주는지 확인한다. */
test.beforeEach(async ({ page }) => { await login(page, "applicant@corp.local", "applicant"); });

test("코딩테스트가 있는 공고: 제목에는 '코딩테스트 포함' 이 없고, 배지·요약·채용 절차·안내에 코딩테스트가 나온다", async ({ page }) => {
  await page.goto("/jobs");
  const card = page.getByTestId("job-card").filter({ hasText: "알고리즘 엔지니어" });
  await expect(card).toContainText("코딩테스트");                                              // 목록 카드에는 배지
  await expect(card.getByRole("heading", { name: "알고리즘 엔지니어", exact: true })).toBeVisible();   // 제목은 공고명 그대로
  await card.click();

  await expect(page.getByRole("heading", { level: 1, name: "알고리즘 엔지니어", exact: true })).toBeVisible();
  await expect(page.getByTestId("coding-badge")).toBeVisible();
  await expect(page.getByTestId("fact-coding")).toHaveText("있음 (제한 30분)");
  await expect(page.getByTestId("job-sections")).toContainText("주요 업무");
  await expect(page.getByTestId("job-sections").locator("li").first()).toBeVisible();               // 줄글이 목록으로
  const steps = page.getByTestId("process-step");
  await expect(steps).toHaveCount(5);
  await expect(steps.nth(3)).toContainText("코딩테스트");
  await expect(steps.nth(3)).toContainText("제한시간 30분");
  await expect(page.getByTestId("guide")).toContainText("Python · Java · JavaScript");
  await expect(page.getByTestId("apply-btn")).toHaveCount(1);                                      // 지원 버튼은 화면에 하나만
});

test("코딩테스트가 없는 공고: 4단계 절차, 코딩테스트 '없음', 코딩 안내 없음, 문의 메일 표기", async ({ page }) => {
  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" }).click();
  await expect(page.getByTestId("process-step")).toHaveCount(4);
  await expect(page.getByTestId("process-step").filter({ hasText: "코딩테스트" })).toHaveCount(0);
  await expect(page.getByTestId("fact-coding")).toHaveText("없음");
  await expect(page.getByTestId("coding-badge")).toHaveCount(0);
  await expect(page.getByTestId("guide")).not.toContainText("Python");
  await expect(page.getByText("hr@corp.local")).toBeVisible();
  await expect(page.getByTestId("process-step").nth(2)).toContainText("꼬리질문 최대 1회");
  await expect(page.getByText(/질문당 답변 최대 60초/)).toBeVisible();
});

test("모바일: 지원 버튼이 화면 아래에 고정되고 본문과 겹치지 않으며 가로로 넘치지 않는다", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await login(page, "applicant@corp.local", "applicant");
  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "알고리즘 엔지니어" }).click();
  // 핵심 요약(코딩테스트 여부 등)이 본문 목록보다 위에 있다
  const factY = (await page.getByTestId("fact-coding").boundingBox())!.y;
  const sectionsY = (await page.getByTestId("job-sections").boundingBox())!.y;
  expect(factY).toBeLessThan(sectionsY);
  const btn = page.getByTestId("apply-btn");
  await expect(btn).toBeVisible();
  const box = await btn.boundingBox();
  expect(box!.y + box!.height).toBeGreaterThan(844 - 80);                                          // 화면 하단에 붙어 있다
  await page.getByTestId("guide").scrollIntoViewIfNeeded();
  await expect(btn).toBeVisible();                                                                 // 스크롤해도 계속 보인다
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await ctx.close();
});

test("담당자 미리보기는 지원자 상세와 같은 구성으로 보인다 (지원 버튼은 비활성)", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await login(page, "hr@corp.local", "recruiter");
  const list = await (await page.request.get("/api/v1/admin/jobs")).json();
  const job = list.items.find((j: { title: string }) => j.title === "알고리즘 엔지니어");
  await page.goto(`/admin/jobs/${job.id}/preview`);
  await expect(page.getByTestId("preview-banner")).toBeVisible();
  await expect(page.getByTestId("process-step")).toHaveCount(5);
  await expect(page.getByTestId("fact-coding")).toHaveText("있음 (제한 30분)");
  await expect(page.getByRole("button", { name: /지원하기/ })).toBeDisabled();
  await ctx.close();
});
