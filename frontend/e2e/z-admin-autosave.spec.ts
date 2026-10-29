import { expect, test, type Page } from "@playwright/test";
import { login } from "./helpers";

/** 공고 작성 자동 저장(UI_SPEC §5.3.2). E2E 는 NEXT_PUBLIC_AUTOSAVE_MS=1500 으로 주기를 줄여 둔다. */
test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ page }) => { await login(page, "hr@corp.local", "recruiter"); });

const stamp = Date.now();
const DEADLINE = () => new Date(Date.now() + 9 * 86400_000).toISOString();
const status = (page: Page) => page.getByTestId("autosave-status");

async function draft(page: Page, title: string) {
  const j = await (await page.request.post("/api/v1/admin/jobs", { data: { title, job_category: "개발", headcount: 1, deadline_at: DEADLINE(), duties: "- 서버", requirements: "- Java" } })).json();
  return j.id as string;
}
const getJob = async (page: Page, id: string) => (await page.request.get(`/api/v1/admin/jobs/${id}`)).json();

test("임시저장 공고: 1단계를 고치면 저장 버튼 없이 서버에 저장되고 '자동 저장됨'이 보인다", async ({ page }) => {
  const id = await draft(page, `자동저장1 ${stamp}`);
  await page.goto(`/admin/jobs/${id}/edit`);
  await page.getByTestId("work-location").fill("강남 본사");
  await expect(status(page)).toContainText("저장되지 않은 변경 사항");
  await expect(status(page)).toContainText(/자동 저장됨 \d{2}:\d{2}/, { timeout: 10_000 });
  expect((await getJob(page, id)).work_location).toBe("강남 본사");
});

test("2단계 자동 저장 뒤 1단계로 돌아가 고쳐도 STALE_UPDATE 없이 저장된다", async ({ page }) => {
  const id = await draft(page, `자동저장2 ${stamp}`);
  await page.goto(`/admin/jobs/${id}/edit?step=2`);
  await page.locator('input[type="number"]').first().fill("90");
  await expect(status(page)).toContainText(/자동 저장됨/, { timeout: 10_000 });
  expect((await getJob(page, id)).answer_time_limit_sec).toBe(90);
  await page.getByRole("button", { name: /1/ }).first().click();
  await page.getByTestId("notice").fill("- 자동 저장 확인");
  await expect(status(page)).toContainText(/자동 저장됨/, { timeout: 10_000 });
  await expect(status(page)).not.toContainText("멈췄어요");
  expect((await getJob(page, id)).notice).toContain("자동 저장 확인");
});

test("게시된 공고는 자동 저장하지 않는다(서버 값 그대로, 저장되지 않음 표시)", async ({ page }) => {
  const id = await draft(page, `자동저장3 ${stamp}`);
  await page.request.put(`/api/v1/admin/jobs/${id}/questions`, { data: { items: Array.from({ length: 10 }, (_, i) => ({ text: `질문 ${i + 1}번을 설명해 주세요` })) } });
  expect((await page.request.post(`/api/v1/admin/jobs/${id}/publish`)).ok()).toBe(true);
  await page.goto(`/admin/jobs/${id}/edit`);
  const field = page.getByTestId("work-location");
  if (await field.isDisabled()) return;                 // 게시된 공고를 잠그는 화면이면 편집 자체가 불가 — 저장될 일이 없다
  await field.fill("몰래 바뀌면 안 되는 값");
  await page.waitForTimeout(3500);
  await expect(status(page)).toContainText("저장되지 않은 변경 사항");
  expect((await getJob(page, id)).work_location).not.toBe("몰래 바뀌면 안 되는 값");
});

test("다른 곳에서 먼저 수정되면 자동 저장을 멈추고 덮어쓰지 않는다", async ({ page }) => {
  const id = await draft(page, `자동저장4 ${stamp}`);
  await page.goto(`/admin/jobs/${id}/edit`);
  await expect(page.getByLabel("공고 제목 *")).toHaveValue(`자동저장4 ${stamp}`);   // 화면이 공고를 다 불러온 뒤에 다른 곳에서 수정한다
  const cur = await getJob(page, id);
  expect((await page.request.put(`/api/v1/admin/jobs/${id}`, { data: { work_location: "다른 탭에서 수정", updated_at: cur.updated_at } })).ok()).toBe(true);
  await page.getByTestId("notice").fill("- 덮어쓰면 안 됨");
  await expect(status(page)).toContainText("멈췄어요", { timeout: 10_000 });
  const after = await getJob(page, id);
  expect(after.work_location).toBe("다른 탭에서 수정");
  expect(after.notice ?? "").not.toContain("덮어쓰면 안 됨");
});

test("새 공고: 새로고침해도 입력이 복원되고, 첫 저장 뒤에는 백업이 지워진다", async ({ page }) => {
  await page.goto("/admin/jobs/new");
  await page.getByLabel("공고 제목 *").fill(`백업 공고 ${stamp}`);
  await page.waitForTimeout(1200);
  await page.reload();
  await expect(page.getByTestId("draft-restored")).toBeVisible();
  await expect(page.getByLabel("공고 제목 *")).toHaveValue(`백업 공고 ${stamp}`);
  await page.getByRole("button", { name: "저장하고 다음 ›" }).click();
  await expect(page).toHaveURL(/\/edit\?step=2/);
  await page.goto("/admin/jobs/new");
  await expect(page.getByTestId("draft-restored")).toHaveCount(0);
  await expect(page.getByLabel("공고 제목 *")).toHaveValue("");
});

test("저장되지 않은 변경이 있으면 창을 닫을 때 확인을 받는다", async ({ page }) => {
  const id = await draft(page, `자동저장6 ${stamp}`);
  await page.goto(`/admin/jobs/${id}/edit`);
  await page.getByTestId("work-location").fill("미저장");
  let asked = false;
  page.on("dialog", async (d) => { asked = d.type() === "beforeunload"; await d.dismiss(); });
  await page.evaluate(() => window.dispatchEvent(new Event("beforeunload", { cancelable: true })));
  const prevented = await page.evaluate(() => { const e = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; });
  expect(prevented || asked).toBe(true);
});
