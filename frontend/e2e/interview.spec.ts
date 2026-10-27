import { expect, test } from "@playwright/test";
import { login, prepareInterview } from "./helpers";

// 같은 세션을 쓰므로 순서에 의존한다: 충돌 시나리오(세션을 끝내지 않음)를 먼저, 끝까지 가는 시나리오를 나중에 실행한다.
test.describe.configure({ mode: "serial" });
let sid = "";

test("준비 REST 체인: 지원 → 이력서 → 세션 → 장치 점검 → 시작", async ({ page }) => {
  await login(page, "applicant@corp.local", "applicant");
  await expect(page).toHaveURL(/\/jobs/);
  sid = await prepareInterview(page);
  const state = await (await page.request.get(`/api/v1/sessions/${sid}/state`)).json();
  expect(state.state).toBe("ready");
  const mine = await (await page.request.get("/api/v1/me/applications")).json();
  expect(mine[0].status).toBe("prepared");
});

test("로그인한 사용자가 /login 에 접근하면 역할별 홈으로 이동한다", async ({ page }) => {
  await login(page, "applicant@corp.local", "applicant");
  await expect(page).toHaveURL(/\/jobs/);
  await page.goto("/login");
  await expect(page).toHaveURL(/\/jobs/);
  await page.context().clearCookies();
  await login(page, "hr@corp.local", "recruiter");
  await expect(page).toHaveURL(/\/admin/);
  await page.goto("/login");
  await expect(page).toHaveURL(/\/admin/);
});

test("다른 창에서 이미 진행 중이면 안내하고 크래시하지 않는다", async ({ browser }) => {
  const mk = async () => { const ctx = await browser.newContext({ permissions: ["camera", "microphone"] }); const page = await ctx.newPage(); await login(page, "applicant@corp.local", "applicant"); return { ctx, page }; };
  const a = await mk(), b = await mk();
  await a.page.goto(`/interview/${sid}`);
  await a.page.getByTestId("start-btn").click();
  await expect(a.page.getByTestId("caption")).toContainText(/\S/, { timeout: 15_000 });
  await b.page.goto(`/interview/${sid}`);
  await b.page.getByTestId("start-btn").click();
  await expect(b.page.getByTestId("failure")).toBeVisible({ timeout: 20_000 });
  await a.ctx.close(); await b.ctx.close();
});

test("지원자: 시작 게이트 → 질문(자막) → 카운트다운 → 답변 → 꼬리질문 → … → 대기 화면, 종료 후 리포트 잡 생성", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, "applicant@corp.local", "applicant");
  await page.goto(`/interview/${sid}`);
  await page.getByTestId("start-btn").click();

  async function answerOnce() {
    await expect(page.getByTestId("caption")).toContainText(/\S/, { timeout: 15_000 });
    await expect(page.getByTestId("countdown")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("answer-timer")).toBeVisible();
    const done = page.getByTestId("answer-done");
    await expect(done).toBeEnabled({ timeout: 10_000 });
    await page.waitForTimeout(2500);  // 서버의 최소 답변 길이(오디오 기준)를 채운다
    await done.click();
    await expect(page.getByTestId("thinking")).toBeVisible();
  }

  await expect(page.getByTestId("caption")).toContainText("1번째 질문", { timeout: 15_000 });
  await answerOnce();
  await expect(page.getByTestId("caption")).toContainText("Redis", { timeout: 30_000 });  // 꼬리질문
  await answerOnce();
  await expect(page.getByTestId("caption")).toContainText("2번째 질문", { timeout: 30_000 });
  await answerOnce();

  await expect(page).toHaveURL(new RegExp(`/interview/${sid}/waiting`), { timeout: 30_000 });
  expect(errors).toEqual([]);

  // POST /finish 는 멱등 — 서버가 종료 시점에 이미 처리했으므로 다시 불러도 같은 결과
  const fin = await page.request.post(`/api/v1/sessions/${sid}/finish`);
  expect(fin.status()).toBe(202);
  expect((await fin.json()).report_status).toBe("queued");
  const mine = await (await page.request.get("/api/v1/me/applications")).json();
  expect(mine[0].status).toBe("interview_done");
  expect(mine[0].report_status).toBe("queued");
});

test("면접을 끝낸 지원자가 관리자 대시보드/상세에 실제 데이터로 나타난다 (음성 Range 포함)", async ({ page, browser }) => {
  const ctx = await browser.newContext();
  const hr = await ctx.newPage();
  await login(hr, "hr@corp.local", "recruiter");
  await expect(hr).toHaveURL(/\/admin/);
  const dash = await (await hr.request.get("/api/v1/admin/dashboard")).json();
  const mine = dash.recent_completed_applicants.find((a: { name: string }) => a.name === "김지원");
  expect(mine, "방금 면접을 마친 지원자").toBeTruthy();
  expect(mine.report_status).toBe("queued");
  const tl = await (await hr.request.get(`/api/v1/admin/applications/${mine.application_id}/timeline`)).json();
  expect(tl.turns.length).toBeGreaterThanOrEqual(3);  // 메인 2 + 꼬리질문 1
  const withAudio = tl.turns.find((t: { audio_url: string | null }) => t.audio_url);
  expect(withAudio, "녹음된 답변 오디오").toBeTruthy();
  const r = await hr.request.get(withAudio.audio_url, { headers: { Range: "bytes=0-43" } });
  expect(r.status()).toBe(206);
  expect((await r.body()).subarray(0, 4).toString()).toBe("RIFF");
  void page;
  await ctx.close();
});
