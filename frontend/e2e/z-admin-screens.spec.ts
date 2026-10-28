import { expect, test, type Page } from "@playwright/test";
import { PASSWORD, login } from "./helpers";

/** 담당자 화면: 일정 캘린더(ADM-07), 이력·알림(ADM-08), 지원자 목록(ADM-04/04b). */
test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ page }) => { await login(page, "hr@corp.local", "recruiter"); });

const localInput = (d: Date) => { const p = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
const tomorrow = (h: number, m = 0) => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(h, m, 0, 0); return d; };

async function addSchedule(page: Page, title: string, start: Date, end?: Date) {
  await page.getByTestId("schedule-add").click();
  const dlg = page.getByRole("dialog", { name: "면접 일정 추가" });
  await dlg.getByLabel("제목").fill(title);
  await dlg.getByLabel("시작").fill(localInput(start));
  if (end) await dlg.getByLabel("종료(선택)").fill(localInput(end));
  return dlg;
}

test("일정: 추가 → 월/주/리스트에 표시 → 겹침 경고(저장은 가능) → 수정 → 삭제", async ({ page }) => {
  await page.goto("/admin/calendar");
  await expect(page.getByTestId("cal-title")).toContainText(`${new Date().getFullYear()}년`);

  const dlg = await addSchedule(page, "캘린더1차", tomorrow(14), tomorrow(15));
  await expect(dlg.getByTestId("overlap-warning")).toHaveCount(0);
  await dlg.getByRole("button", { name: "추가" }).click();
  const chip = page.getByTestId("schedule-chip").filter({ hasText: "캘린더1차" });
  await expect(chip).toBeVisible();

  // 같은 시간대에 추가하면 경고하지만 막지 않는다
  const dlg2 = await addSchedule(page, "캘린더겹침", tomorrow(14, 30), tomorrow(15, 30));
  await expect(dlg2.getByTestId("overlap-warning")).toContainText("캘린더1차");
  await dlg2.getByRole("button", { name: "추가" }).click();
  await expect(page.getByTestId("schedule-chip").filter({ hasText: "캘린더겹침" })).toBeVisible();

  // 종료가 시작보다 빠르면 저장되지 않는다
  const bad = await addSchedule(page, "잘못된 일정", tomorrow(16), tomorrow(15));
  await bad.getByRole("button", { name: "추가" }).click();
  await expect(bad.getByText("종료는 시작 이후여야 해요")).toBeVisible();
  await bad.getByRole("button", { name: "취소" }).click();

  // 주 보기 / 리스트 보기
  await page.getByRole("button", { name: "주", exact: true }).click();
  await expect(page.getByTestId("week-grid").getByText("캘린더1차")).toBeVisible();
  await page.getByRole("button", { name: "리스트" }).click();
  await expect(page.getByTestId("list-view")).toContainText("캘린더겹침");
  await page.getByRole("button", { name: "월", exact: true }).click();

  // 수정
  await chip.click();
  const edit = page.getByRole("dialog", { name: "일정 수정" });
  await edit.getByLabel("제목").fill("캘린더1차 (일정 변경)");
  await edit.getByRole("button", { name: "저장" }).click();
  await expect(page.getByTestId("schedule-chip").filter({ hasText: "일정 변경" })).toBeVisible();
  await expect(page.getByTestId("schedule-chip").filter({ hasText: /캘린더1차$/ })).toHaveCount(0);

  // 삭제 (확인 대화상자)
  for (const t of ["일정 변경", "캘린더겹침"]) {
    await page.getByTestId("schedule-chip").filter({ hasText: t }).click();
    page.once("dialog", (d) => void d.accept());
    await page.getByTestId("schedule-delete").click();
    await expect(page.getByTestId("schedule-chip").filter({ hasText: t })).toHaveCount(0);
  }
  const left = await (await page.request.get("/api/v1/admin/schedules")).json();
  expect(left.filter((s: { title: string }) => s.title.startsWith("캘린더")).length).toBe(0);

  // 이전/다음 달
  const before = await page.getByTestId("cal-title").textContent();
  await page.getByRole("button", { name: "다음" }).click();
  await expect(page.getByTestId("cal-title")).not.toHaveText(before!);
  await page.getByRole("button", { name: "오늘" }).click();
  await expect(page.getByTestId("cal-title")).toHaveText(before!);
});

test("알림: 새 지원 알림이 쌓이고, 클릭하면 읽음 처리되며 해당 화면으로 이동한다 / 공고 이력 탭", async ({ page, browser }) => {
  let job: { id: string } = { id: "" };
  async function applyAsNewUser(tag: string) {
    const ctx = await browser.newContext();
    const ap = await ctx.newPage();
    const email = `noti-${tag}-${Date.now()}@corp.local`;
    expect((await ap.request.post("/api/v1/auth/register", { data: { name: "알림지원자", email, password: PASSWORD, password_confirm: PASSWORD, birth_date: "1999-01-01", gender: "female", phone: "010-2222-3333" } })).status()).toBe(201);
    job = (await (await ap.request.get("/api/v1/jobs")).json()).items.find((j: { title: string }) => j.title.startsWith("백엔드"));
    expect((await ap.request.post(`/api/v1/jobs/${job.id}/apply`, { data: { consent: true, consent_version: "2026-01" } })).status()).toBe(201);
    await ctx.close();
  }
  await applyAsNewUser("a");

  const unreadBefore = (await (await page.request.get("/api/v1/admin/notifications")).json()).unread_count;
  expect(unreadBefore).toBeGreaterThan(0);
  await page.goto("/admin/history");
  await expect(page.getByRole("link", { name: new RegExp(`알림 ${unreadBefore}건`) })).toBeVisible();   // 헤더 벨 배지
  const item = page.getByTestId("notification-item").filter({ hasText: "새 지원이 들어왔어요" }).first();
  await expect(item).toBeVisible();
  await expect(item.getByLabel("읽지 않음")).toBeVisible();
  await expect(page.getByTestId("notification-list")).not.toContainText("알림지원자");                  // 이름은 알림에 담기지 않는다
  await item.click();
  await expect(page).toHaveURL(new RegExp(`/admin/jobs/${job.id}/applicants`));
  await expect.poll(async () => (await (await page.request.get("/api/v1/admin/notifications")).json()).unread_count).toBe(unreadBefore - 1);

  await applyAsNewUser("b");                                                                             // 읽지 않은 알림이 다시 생기면 [모두 읽음] 으로 한 번에 처리한다
  await page.goto("/admin/history");
  await page.getByTestId("read-all").click();
  await expect.poll(async () => (await (await page.request.get("/api/v1/admin/notifications")).json()).unread_count).toBe(0);

  expect((await page.request.post("/api/v1/admin/jobs", { data: { title: "이력 확인용 공고" } })).status()).toBe(201);
  await page.getByRole("tab", { name: "공고 이력" }).click();
  await expect(page).toHaveURL(/tab=jobs/);
  const table = page.getByTestId("history-table");
  await expect(table.locator("tbody tr").filter({ hasText: "이력 확인용 공고" })).toContainText("작성");
  await expect(table).toContainText("박담당");
});

test("지원자 목록: 통합 목록의 정렬·필터·비교 모드, 공고별 목록, 상세 이동", async ({ page }) => {
  await page.goto("/admin/applicants");
  const table = page.getByTestId("applicant-table");
  for (const n of ["이도윤", "최서연", "정하늘"]) await expect(table).toContainText(n);

  await page.getByTestId("sort").selectOption("score_desc");
  await expect(page).toHaveURL(/sort=score_desc/);
  await expect(table.locator("tbody tr").first()).toContainText("이도윤");                              // 82.5 가 맨 위, 점수 없는 지원자는 뒤

  await page.getByTestId("name-filter").fill("서연");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await page.getByTestId("name-filter").fill("");
  await page.getByLabel("최종 결정").selectOption("pass");
  await expect(page.getByText("조건에 맞는 지원자가 없어요")).toBeVisible();
  await page.getByLabel("최종 결정").selectOption("");

  // 비교 모드: 리포트 완료만 선택 가능, 2명 선택해야 비교 버튼이 켜진다
  await page.getByRole("button", { name: "비교 모드 켜기" }).click();
  await expect(page.getByLabel("정하늘 비교 선택")).toBeDisabled();
  await page.getByLabel("이도윤 비교 선택").check();
  await expect(page.getByRole("link", { name: "선택한 지원자 비교하기" })).toHaveAttribute("aria-disabled", "true");
  await page.getByLabel("최서연 비교 선택").check();
  await page.getByRole("link", { name: "선택한 지원자 비교하기" }).click();
  await expect(page).toHaveURL(/\/admin\/applicants\/compare\?ids=/);

  // 공고별 목록: 그 공고의 지원자만, 공고 열은 숨김
  await page.goto("/admin/jobs");
  await page.getByRole("row", { name: /백엔드 개발자/ }).getByRole("link", { name: /명 보기/ }).click();
  await expect(page).toHaveURL(/\/admin\/jobs\/[^/]+\/applicants/);
  await expect(page.getByTestId("applicants-title")).toContainText("백엔드 개발자");
  await expect(page.getByTestId("applicant-table")).toContainText("이도윤");
  await expect(page.getByTestId("applicant-table")).not.toContainText("코딩지원자");                     // 다른 공고 지원자는 섞이지 않는다
  await expect(page.getByRole("columnheader", { name: "공고" })).toHaveCount(0);
  await page.getByRole("link", { name: "메모" }).first().click();
  await expect(page).toHaveURL(/tab=notes/);
  await expect(page.getByTestId("notes-tab")).toBeVisible();
});

test("좁은 화면(모바일)에서는 캘린더가 리스트 보기로 열리고, 일정 추가 버튼이 보인다", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await login(page, "hr@corp.local", "recruiter");
  await page.goto("/admin/calendar");
  await expect(page.getByRole("button", { name: "리스트" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("schedule-add")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);   // 가로 스크롤이 생기지 않는다
  await ctx.close();
});
