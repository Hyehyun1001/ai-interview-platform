import path from "node:path";
import { expect, test } from "@playwright/test";

/**
 * 실제 엔진(Ollama · bge-m3 · faster-whisper)으로 지원자 사전 준비 화면을 **UI 만으로** 끝까지 확인한다:
 * 공고 → 동의 → 실제 PDF 업로드/추출 → 장치 점검(마이크 = 실제 한국어 음성 파일) → 면접 시작 대기(모델 warm-up) → 첫 질문.
 * 관측값은 이 실행의 값일 뿐이다. 실제 웹캠·얼굴은 자동화할 수 없어 카메라는 패턴 영상(얼굴 없음)이다.
 */
test("실제 엔진: 지원자가 UI 로 공고 지원 → PDF 이력서 → 장치 점검 → 면접 첫 질문까지", async ({ page }) => {
  test.setTimeout(10 * 60_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const email = `real-ui-${Date.now()}@corp.local`;
  expect((await page.request.post("/api/v1/auth/register", { data: { name: "실엔진", email, password: "Passw0rd!", password_confirm: "Passw0rd!", birth_date: "1999-01-01", gender: "female", phone: "010-1111-2222" } })).status()).toBe(201);

  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" }).click();
  await page.getByTestId("apply-btn").click();
  const dialog = page.getByRole("dialog", { name: "개인정보 활용 동의" });
  await dialog.getByLabel(/개인정보 수집·이용에 동의/).check();
  await dialog.getByLabel(/녹화·저장 및 AI 평가에 동의/).check();
  await dialog.getByRole("button", { name: "동의하고 계속" }).click();
  await expect(page).toHaveURL(/\/resume$/);

  // 실제 PDF → PyMuPDF → 실제 LLM 구조화 추출. UI 는 60초 뒤 "오래 걸려요"를 보여 주므로 계속 기다린다.
  const t0 = Date.now();
  await page.getByTestId("pdf-input").setInputFiles(path.resolve(__dirname, "fixtures/resume-ko.pdf"));
  const banner = page.getByTestId("extracted-banner");
  for (let i = 0; i < 6 && !(await banner.isVisible()); i++) {
    await Promise.race([banner.waitFor({ timeout: 70_000 }), page.getByRole("button", { name: "계속 기다리기" }).click({ timeout: 70_000 })]).catch(() => undefined);
  }
  await expect(banner).toBeVisible();
  console.log(`[real-ui] 추출 완료 ${((Date.now() - t0) / 1000).toFixed(1)}s, 배너="${(await banner.textContent())?.trim()}"`);
  const got = { name: await page.getByLabel("성명").inputValue(), school: await page.getByLabel("학교명 1", { exact: true }).inputValue(), skills: await page.getByRole("list", { name: "기술 목록" }).locator("li").count() };
  console.log(`[real-ui] 폼에 채워진 값: name="${got.name}" school="${got.school}" skills=${got.skills}`);
  if (!got.name) await page.getByLabel("성명").fill("실엔진");              // 추출하지 못한 필수 항목은 지원자가 직접 채운다
  if (!got.school) await page.getByLabel("학교명 1", { exact: true }).fill("한빛대학교");
  await page.getByTestId("next-btn").click();
  await expect(page).toHaveURL(/\/device-check$/);

  const status = (s: string) => page.getByTestId(`step-${s}`);
  await expect(status("camera")).toHaveAttribute("data-status", "pass", { timeout: 30_000 });
  await expect(status("mic")).toHaveAttribute("data-status", "pass", { timeout: 30_000 });   // 실제 음성 파일이 마이크로 들어온다
  await page.getByTestId("play-guide").click();
  await page.getByTestId("heard-yes").click();
  await expect(page.getByTestId("start-interview")).toBeEnabled({ timeout: 15_000 });

  const stages = new Set<string>();
  const t1 = Date.now();
  await page.getByTestId("start-interview").click();
  const overlay = page.getByTestId("starting-overlay");
  while (!/\/interview\//.test(page.url()) && Date.now() - t1 < 120_000) {
    if (await overlay.isVisible().catch(() => false)) stages.add((await page.getByTestId("start-stage").textContent().catch(() => "")) ?? "");
    await page.waitForTimeout(500);
  }
  await expect(page).toHaveURL(/\/interview\/[0-9a-f-]+$/);
  console.log(`[real-ui] 면접 시작 대기 ${((Date.now() - t1) / 1000).toFixed(1)}s, 관측한 안내 문구=${JSON.stringify([...stages].map((s) => s.replace(/ · \d+초/, "")))}`);

  await page.getByTestId("start-btn").click();
  await expect(page.getByTestId("caption")).toContainText(/\S/, { timeout: 90_000 });
  console.log(`[real-ui] 첫 질문 자막: ${(await page.getByTestId("caption").textContent())?.slice(0, 80)}`);
  expect(errors).toEqual([]);
});
