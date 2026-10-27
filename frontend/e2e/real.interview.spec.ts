import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { login, prepareInterview } from "./helpers";

/**
 * 실제 모델(Ollama · faster-whisper turbo · say)로 지원자 → 관리자 흐름을 끝까지 확인한다.
 * 수치는 이 실행에서 *관측한 값*일 뿐이다(표본 3~6회). TRD V-3 의 100회 측정을 대체하지 않는다.
 */
test("실제 모델: 면접 진행 → 종료 → 관리자 화면에서 실제 전사·오디오 확인", async ({ page, browser }) => {
  test.setTimeout(15 * 60_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // 질문 음성 재생이 시작되는 시각을 기록한다 (answer_end → 다음 질문 음성 시작 지연 측정)
  await page.addInitScript(() => {
    const w = window as unknown as { __play: number[] };
    w.__play = [];
    const orig = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function (...a) { w.__play.push(performance.now()); return orig.apply(this, a); };
  });

  await login(page, "applicant@corp.local", "applicant");
  // 실제 PDF 업로드 → PyMuPDF 파싱 → 실제 LLM 구조화 추출 (마이페이지 등록본)
  const up = await page.request.post("/api/v1/me/resume/upload", { multipart: { file: { name: "resume.pdf", mimeType: "application/pdf", buffer: readFileSync(path.resolve(__dirname, "fixtures/resume-ko.pdf")) } } });
  expect(up.status()).toBe(202);
  const jobId = (await up.json()).job_id as string;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/resume-jobs/${jobId}`)).json()).status, { timeout: 180_000 }).not.toBe("running");
  const ext = await (await page.request.get(`/api/v1/resume-jobs/${jobId}`)).json();
  console.log(`[real] PDF 추출: status=${ext.status} fell_back=${ext.fell_back} dropped=${ext.dropped} name=${ext.data?.name} edu=${ext.data?.education?.length} exp=${ext.data?.experience?.length} proj=${ext.data?.projects?.length} skills=${ext.data?.skills?.length}`);
  expect(ext.status).toBe("done");
  const t0 = Date.now();
  const sid = await prepareInterview(page, "mypage");  // 마이페이지 등록본(PDF 추출 결과)으로 지원 — 실제 LLM warm-up 포함
  console.log(`[real] 준비(세션 생성~warm-up 완료): ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  const state = await (await page.request.get(`/api/v1/sessions/${sid}/state`)).json();
  console.log(`[real] degraded_mode=${state.degraded_mode} total_main=${state.total_main}`);

  await page.goto(`/interview/${sid}`);
  await page.getByTestId("start-btn").click();

  const latencies: number[] = [];
  const captions: string[] = [];
  for (let n = 0; n < 9; n++) {  // 메인 3 + 질문당 꼬리질문 최대 1 = 최대 6턴 (여유 2)
    await expect(page.getByTestId("caption")).toContainText(/\S/, { timeout: 90_000 });
    captions.push((await page.getByTestId("caption").textContent()) ?? "");
    await expect(page.getByTestId("countdown")).toBeVisible({ timeout: 60_000 });
    const done = page.getByTestId("answer-done");
    await expect(done).toBeEnabled({ timeout: 20_000 });
    await page.waitForTimeout(14_000);  // 실제 음성 약 14초 분량을 말한다
    const prevCaption = captions[captions.length - 1];
    const clickedAt = await page.evaluate(() => performance.now());
    await done.click();
    await expect(page.getByTestId("thinking")).toBeVisible();
    // 다음 질문이 도착하거나 면접이 끝날 때까지
    const next = await Promise.race([
      page.waitForURL(/\/waiting/, { timeout: 180_000 }).then(() => "end" as const),
      page.waitForFunction((prev) => document.querySelector('[data-testid="caption"]')?.textContent !== prev, prevCaption, { timeout: 180_000 }).then(() => "next" as const),
    ]);
    if (next === "end") break;
    // 다음 질문 음성(play) 호출 시각 − 답변 종료 클릭 시각
    await expect.poll(async () => page.evaluate((c) => (window as unknown as { __play: number[] }).__play.filter((t) => t > c).length, clickedAt), { timeout: 60_000 }).toBeGreaterThan(0);
    const firstPlay = await page.evaluate((c) => (window as unknown as { __play: number[] }).__play.find((t) => t > c) ?? 0, clickedAt);
    latencies.push((firstPlay - clickedAt) / 1000);
    console.log(`[real] 턴 ${n + 1}: answer_end→다음 질문 음성 ${latencies[latencies.length - 1]!.toFixed(2)}s · 다음 질문: ${((await page.getByTestId("caption").textContent()) ?? "").slice(0, 60)}`);
  }
  await expect(page).toHaveURL(new RegExp(`/interview/${sid}/waiting`), { timeout: 60_000 });
  expect(errors).toEqual([]);
  console.log(`[real] 질문 자막: ${JSON.stringify(captions)}`);
  console.log(`[real] answer_end→다음 질문 음성 시작 관측값(초): ${latencies.map((x) => x.toFixed(2)).join(", ")} (표본 ${latencies.length})`);

  // 관리자 관점: 실제 STT 전사와 녹음이 저장되었는지
  // 리포트 워커(임베디드)가 실제 LLM 으로 리포트를 만든다 — 지원자 조회 API 로 완료까지 대기
  const t1 = Date.now();
  await expect.poll(async () => { const r = await page.request.get(`/api/v1/sessions/${sid}/report`); return (await r.json()).status; }, { timeout: 480_000, intervals: [3000] }).toMatch(/done|failed/);
  const rep = await (await page.request.get(`/api/v1/sessions/${sid}/report`)).json();
  console.log(`[real] 리포트 ${rep.status} (종료 후 ${((Date.now() - t1) / 1000).toFixed(0)}s): total=${rep.report?.total_score} criteria=${JSON.stringify(rep.report?.criteria?.map((c: { criterion: string; score: number }) => `${c.criterion}:${c.score}`))}`);
  console.log(`[real] 총평: ${rep.report?.summary}`);
  expect(rep.status).toBe("done");
  await page.goto(`/reports/${sid}`);
  await expect(page.getByTestId("total-score")).toBeVisible();
  const ctx = await browser.newContext();
  const hr = await ctx.newPage();
  await login(hr, "hr@corp.local", "recruiter");
  const dash = await (await hr.request.get("/api/v1/admin/dashboard")).json();
  const mine = dash.recent_completed_applicants.find((a: { name: string }) => a.name === "김지원");
  expect(mine).toBeTruthy();
  const tl = await (await hr.request.get(`/api/v1/admin/applications/${mine.application_id}/timeline`)).json();
  const texts = tl.turns.map((t: { answer_text: string | null }) => t.answer_text ?? "");
  console.log(`[real] 전사 길이(자): ${texts.map((t: string) => t.length).join(", ")}`);
  console.log(`[real] 전사 예시(첫 80자): ${texts[0]?.slice(0, 80)}`);
  expect(texts.some((t: string) => /캐시|레디스|결제|주문|응답/.test(t))).toBe(true);
  for (const t of tl.turns) {
    if (!t.audio_url) continue;
    const r = await hr.request.get(t.audio_url, { headers: { Range: "bytes=0-43" } });
    expect(r.status()).toBe(206);
  }
  await ctx.close();
});
