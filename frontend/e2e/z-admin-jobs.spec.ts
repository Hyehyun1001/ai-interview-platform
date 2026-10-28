import { expect, test, type Page } from "@playwright/test";
import { PASSWORD, login } from "./helpers";

/** 공고 관리 목록(ADM-02)과 공고 작성(ADM-03 1단계: 표기 항목 + 지원자 화면 실시간 미리보기). */
test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ page }) => { await login(page, "hr@corp.local", "recruiter"); });

const stamp = Date.now();
const DEADLINE = () => new Date(Date.now() + 9 * 86400_000).toISOString();

async function publishViaRest(page: Page, title: string, extra: Record<string, unknown> = {}) {
  const j = await (await page.request.post("/api/v1/admin/jobs", { data: { title, job_category: "개발", headcount: 1, deadline_at: DEADLINE(), duties: "- 서버 개발\n- 장애 대응", requirements: "- Java 경험", ...extra } })).json();
  expect((await page.request.put(`/api/v1/admin/jobs/${j.id}/questions`, { data: { items: Array.from({ length: 10 }, (_, i) => ({ text: `${title} 질문 ${i + 1}번을 설명해 주세요` })) } })).ok()).toBe(true);
  expect((await page.request.post(`/api/v1/admin/jobs/${j.id}/publish`)).ok()).toBe(true);
  return j.id as string;
}

test("목록: 상태 탭(개수)·코딩테스트 ON/OFF·현황·검색, 탭은 URL 에 유지된다", async ({ page }) => {
  // 다른 테스트가 만든 공고가 섞여 있어도 되도록 개수는 API 로 센 값과 비교한다
  const all = (await (await page.request.get("/api/v1/admin/jobs?limit=100")).json()).items as { status: string }[];
  const n = (st: string) => all.filter((j) => j.status === st).length;
  await page.goto("/admin/jobs");
  await expect(page.getByTestId("tab-open")).toContainText(`진행 중 (${n("open")})`);
  await expect(page.getByTestId("tab-closed")).toContainText(`마감 (${n("closed")})`);
  await expect(page.getByTestId("tab-draft")).toContainText(`임시저장 (${n("draft")})`);
  const cards = page.getByTestId("job-card-admin");
  await expect(cards).toHaveCount(n("open"));
  const algo = cards.filter({ hasText: "알고리즘 엔지니어" });
  const back = cards.filter({ hasText: "백엔드 개발자" });
  await expect(algo.getByTestId("coding-flag")).toContainText("ON");
  await expect(back.getByTestId("coding-flag")).toContainText("OFF");
  await expect(back.getByTestId("applicant-count")).toHaveText(/^[1-9]\d*$/);                    // 시드의 면접 완료 지원자
  await expect(back).toContainText("미검토");
  await expect(back.getByRole("link", { name: "지원자", exact: true })).toBeVisible();
  // [지원자] 버튼은 지원자가 있는 공고에만 있다 (다른 테스트가 먼저 지원을 만들었을 수 있어 개수를 읽어 판단한다)
  const algoApplicants = Number(await algo.getByTestId("applicant-count").textContent());
  await expect(algo.getByRole("link", { name: "지원자", exact: true })).toHaveCount(algoApplicants > 0 ? 1 : 0);

  await page.getByTestId("job-search").fill("알고리즘");
  await expect(cards).toHaveCount(1);
  await page.getByTestId("job-search").fill("없는공고");
  await expect(page.getByText("검색 결과가 없어요")).toBeVisible();
  await page.getByTestId("job-search").fill("");

  await page.getByTestId("tab-closed").click();
  await expect(page).toHaveURL(/status=closed/);
  await expect(page.getByTestId("job-card-admin").filter({ hasText: "백엔드 개발자" })).toHaveCount(0);   // 진행 중 공고는 마감 탭에 없다
  await page.reload();
  await expect(page.getByTestId("tab-closed")).toHaveAttribute("aria-selected", "true");
});

test("마감: 확인 후 마감 탭으로 이동하고 다시 열 수 없다 / 삭제: 공고명을 입력해야 활성화된다", async ({ page }) => {
  const title = `마감 테스트 ${stamp}`;
  await publishViaRest(page, title);
  const draftTitle = `삭제 테스트 ${stamp}`;
  expect((await page.request.post("/api/v1/admin/jobs", { data: { title: draftTitle } })).status()).toBe(201);

  await page.goto("/admin/jobs");
  const card = page.getByTestId("job-card-admin").filter({ hasText: title });
  await card.getByTestId("close-job").click();
  const dlg = page.getByRole("dialog", { name: "공고를 마감할까요?" });
  await expect(dlg).toContainText("다시 열 수 없어요");
  await dlg.getByRole("button", { name: "취소" }).click();
  await expect(card).toBeVisible();                                                               // 취소하면 그대로
  await card.getByTestId("close-job").click();
  await page.getByTestId("close-confirm").click();
  await expect(card).toHaveCount(0);                                                              // 진행 중 탭에서 사라진다
  await page.getByTestId("tab-closed").click();
  const closed = page.getByTestId("job-card-admin").filter({ hasText: title });
  await expect(closed).toBeVisible();
  await expect(closed.getByRole("link", { name: "수정", exact: true })).toHaveCount(0);           // 마감 공고는 수정 불가
  await expect(closed.getByTestId("close-job")).toHaveCount(0);

  await page.getByTestId("tab-draft").click();
  const draft = page.getByTestId("job-card-admin").filter({ hasText: draftTitle });
  await draft.getByTestId("delete-job").click();
  const del = page.getByRole("dialog", { name: "공고를 삭제할까요?" });
  const ok = page.getByTestId("delete-confirm");
  await expect(ok).toBeDisabled();
  await page.getByTestId("delete-confirm-input").fill("다른 이름");
  await expect(ok).toBeDisabled();
  await page.getByTestId("delete-confirm-input").fill(draftTitle);
  await expect(ok).toBeEnabled();
  await ok.click();
  await expect(del).toBeHidden();
  await expect(draft).toHaveCount(0);
  const list = await (await page.request.get("/api/v1/admin/jobs")).json();
  expect(list.items.some((j: { title: string }) => j.title === draftTitle)).toBe(false);
});

test("삭제: 지원자가 있는 공고는 경고가 강화된다", async ({ page }) => {
  await page.goto("/admin/jobs");
  await page.getByTestId("job-card-admin").filter({ hasText: "백엔드 개발자" }).getByTestId("delete-job").click();
  await expect(page.getByRole("alert").filter({ hasText: "지원자가" })).toBeVisible();
  await expect(page.getByTestId("delete-confirm")).toBeDisabled();
  await page.keyboard.press("Escape");                                                            // 취소: 삭제하지 않는다
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("공고 작성 1단계: 근무지·고용 형태·급여·복리후생·유의 사항을 입력하면 지원자 화면 미리보기에 바로 반영된다", async ({ page }) => {
  await page.goto("/admin/jobs/new");
  const preview = page.getByTestId("live-preview");
  await expect(preview).toBeVisible();
  await expect(page.getByText("AI 질문 근거").first()).toBeVisible();                            // 어떤 항목이 AI 질문에 쓰이는지 표시
  await expect(page.getByText("표시용").first()).toBeVisible();

  await page.getByLabel("공고 제목 *").fill(`표기 정보 공고 ${stamp}`);
  await expect(preview).toContainText(`표기 정보 공고 ${stamp}`);
  await page.getByTestId("employment-type").selectOption("intern");
  await page.getByTestId("work-location").fill("판교 테크노밸리");
  await page.getByTestId("salary-text").fill("면접 후 협의");
  await page.getByTestId("benefits").fill("- 점심 식대 지원\n- 자기계발비");
  await page.getByTestId("notice").fill("- 서류 합격자에게 개별 안내");
  await expect(preview.getByTestId("fact-employment")).toHaveText("인턴");
  await expect(preview.getByTestId("fact-location")).toHaveText("판교 테크노밸리");
  await expect(preview.getByTestId("fact-salary")).toHaveText("면접 후 협의");
  await expect(preview.getByText("점심 식대 지원")).toBeVisible();
  await expect(preview.getByTestId("notice")).toContainText("서류 합격자에게 개별 안내");
  await expect(preview.getByRole("button", { name: /지원하기/ })).toBeDisabled();

  await page.getByRole("button", { name: "저장하고 다음 ›" }).click();
  await expect(page).toHaveURL(/\/edit\?step=2/);
  const list = await (await page.request.get("/api/v1/admin/jobs")).json();
  const saved = list.items.find((j: { title: string }) => j.title === `표기 정보 공고 ${stamp}`);
  const job = await (await page.request.get(`/api/v1/admin/jobs/${saved.id}`)).json();
  expect([job.employment_type, job.work_location, job.salary_text]).toEqual(["intern", "판교 테크노밸리", "면접 후 협의"]);
  expect(job.benefits).toContain("자기계발비");
});

test("게시한 공고의 표기 정보가 지원자 상세에 보인다", async ({ page, browser }) => {
  const title = `지원자 노출 확인 ${stamp}`;
  await publishViaRest(page, title, { employment_type: "contract", work_location: "서울 마포구", salary_text: "회사 내규에 따름", benefits: "- 4대 보험\n- 유연 근무", notice: "- 최종 합격자에게 별도 연락" });
  const ctx = await browser.newContext();
  const ap = await ctx.newPage();
  await ap.request.post("/api/v1/auth/register", { data: { name: "노출확인", email: `view-${stamp}@corp.local`, password: PASSWORD, password_confirm: PASSWORD, birth_date: "1999-01-01", gender: "male", phone: "010-4444-5555" } });
  await ap.goto("/jobs");
  await ap.getByTestId("job-card").filter({ hasText: title }).click();
  await expect(ap.getByTestId("fact-employment")).toHaveText("계약직");
  await expect(ap.getByTestId("fact-location")).toHaveText("서울 마포구");
  await expect(ap.getByTestId("fact-salary")).toHaveText("회사 내규에 따름");
  await expect(ap.getByTestId("job-sections")).toContainText("복리후생");
  await expect(ap.getByTestId("job-sections")).toContainText("유연 근무");
  await expect(ap.getByTestId("notice")).toContainText("최종 합격자에게 별도 연락");
  await ctx.close();
});
