import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import path from "node:path";

/**
 * 지원자 전 과정을 브라우저 UI 로 검증한다: 공고 목록 → 상세 → 동의 → 이력서(PDF/직접 작성) → 장치 점검 3단계 → 면접 화면 진입.
 * 가짜 엔진 스택이라 PDF 추출 결과는 비어 있고(fell_back), 직접 입력으로 채우는 경로를 함께 검증한다.
 * 카메라·마이크는 Chromium 가짜 장치(얼굴 없음)이므로 얼굴 검출/정면 보정의 성공 경로는 여기서 검증하지 못한다.
 */
test.describe.configure({ mode: "serial" });

const EMAIL = `journey-${Date.now()}@corp.local`;
const errors: string[] = [];
let appUrl = "";

// 한 지원자의 여정이므로 쿠키(로그인)를 테스트 사이에 유지하는 공용 컨텍스트를 쓴다
let ctx: BrowserContext;
let page: Page;
test.beforeAll(async ({ browser }) => {
  ctx = await browser.newContext({ permissions: ["camera", "microphone"] });
  page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
});
test.afterAll(async () => { await ctx.close(); });

test("가입한 지원자: 공고 목록 필터·검색이 URL 에 남고 새로고침해도 유지된다", async () => {
  const reg = await page.request.post("/api/v1/auth/register", { data: { name: "여정테스트", email: EMAIL, password: "Passw0rd!", password_confirm: "Passw0rd!", birth_date: "1999-01-01", gender: "female", phone: "010-1234-5678" } });
  expect(reg.status()).toBe(201);

  await page.goto("/jobs");
  const card = page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("개발");
  await expect(page.getByTestId("dday").first()).toContainText(/D-/);
  await expect(card).not.toContainText("지원 완료");

  await page.getByRole("button", { name: "디자인" }).click();
  await expect(page).toHaveURL(/category=%EB%94%94%EC%9E%90%EC%9D%B8/);
  await expect(page.getByText("조건에 맞는 공고가 없습니다")).toBeVisible();
  await page.getByRole("button", { name: "필터 초기화" }).click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(card).toBeVisible();

  await page.getByLabel("공고 검색").fill("백엔드");
  await page.getByRole("button", { name: "검색" }).click();
  await expect(page).toHaveURL(/q=%EB%B0%B1%EC%97%94%EB%93%9C/);
  await page.reload();
  await expect(page.getByLabel("공고 검색")).toHaveValue("백엔드");  // URL 이 단일 진실 원천
  await expect(card).toBeVisible();

  await page.getByLabel("공고 검색").fill("존재하지않는키워드zzz");
  await page.getByRole("button", { name: "검색" }).click();
  await expect(page.getByText("조건에 맞는 공고가 없습니다")).toBeVisible();
});

test("공고 상세 → 동의 모달은 두 항목을 모두 체크해야 진행되고, 취소하면 지원이 생기지 않는다", async () => {
  await page.goto("/jobs");
  await page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" }).click();
  await expect(page.getByRole("heading", { name: /백엔드 개발자/ })).toBeVisible();
  await expect(page.getByText("주요 업무")).toBeVisible();
  await expect(page.getByText("내부망 서버에서만 처리")).toBeVisible();

  await page.getByTestId("apply-btn").click();
  const dialog = page.getByRole("dialog", { name: "개인정보 활용 동의" });
  const go = dialog.getByRole("button", { name: "동의하고 계속" });
  await expect(go).toBeDisabled();
  await dialog.getByLabel(/개인정보 수집·이용에 동의/).check();
  await expect(go).toBeDisabled();                       // 하나만 체크하면 비활성
  await dialog.getByLabel(/녹화·저장 및 AI 평가에 동의/).check();
  await expect(go).toBeEnabled();
  await page.keyboard.press("Escape");                   // ESC 로 닫기 = 취소
  await expect(dialog).toBeHidden();
  expect((await (await page.request.get("/api/v1/me/applications")).json())).toHaveLength(0);

  await page.getByTestId("apply-btn").click();
  await expect(go).toBeDisabled();                       // 다시 열면 체크가 초기화된다
  await dialog.getByLabel(/개인정보 수집·이용에 동의/).check();
  await dialog.getByLabel(/녹화·저장 및 AI 평가에 동의/).check();
  await go.click();
  await expect(page).toHaveURL(/\/apply\/[0-9a-f-]+\/resume/);
  appUrl = page.url().replace(/\/resume.*/, "");
});

test("이력서 단계: 비PDF 는 요청 없이 차단, PDF 업로드 후 기본 정보를 채워야 다음으로 간다", async () => {
  let uploads = 0;
  page.on("request", (r) => { if (r.url().includes("/resume/upload")) uploads++; });
  await page.goto(`${appUrl}/resume`);
  await expect(page.getByRole("heading", { name: /백엔드 개발자/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: /PDF 새로 첨부/ })).toBeChecked();   // 등록본이 없으면 PDF 첨부가 기본
  await expect(page.getByRole("radio", { name: /마이페이지 등록본/ })).toHaveCount(0);
  await expect(page.getByTestId("next-btn")).toBeDisabled();

  const input = page.getByTestId("pdf-input");
  await input.setInputFiles({ name: "resume.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("x") });
  await expect(page.getByTestId("dropzone-error")).toHaveText("PDF 파일만 업로드할 수 있습니다.");
  await input.setInputFiles({ name: "big.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
  await expect(page.getByTestId("dropzone-error")).toContainText("10MB");
  expect(uploads).toBe(0);                                                        // 업로드 요청 자체가 나가지 않았다

  await input.setInputFiles(path.join(__dirname, "fixtures/resume-ko.pdf"));
  await expect(page.getByTestId("extracted-banner")).toContainText("자동 추출된 값입니다", { timeout: 30_000 });
  expect(uploads).toBe(1);
  await expect(page.getByTestId("next-btn")).toBeDisabled();                      // 성명·학력/경력이 비어 있다
  await expect(page.getByTestId("basic-info-warning")).toBeVisible();

  await page.getByLabel("성명").fill("여정테스트");
  await expect(page.getByTestId("next-btn")).toBeDisabled();                      // 성명만으로는 부족
  await page.getByLabel("학교명 1", { exact: true }).fill("한빛대학교");
  await page.getByLabel("전공 1", { exact: true }).fill("컴퓨터공학");
  await expect(page.getByTestId("next-btn")).toBeEnabled();
  await page.getByLabel("기술 입력").fill("Java");
  await page.getByRole("button", { name: "추가", exact: true }).first().click();
  await expect(page.getByRole("list", { name: "기술 목록" })).toContainText("Java");
  await page.getByLabel("이 이력서를 마이페이지에도 저장").check();

  await page.getByTestId("next-btn").click();
  await expect(page).toHaveURL(/\/device-check$/);

  // 서버에는 지원용 스냅샷과 마이페이지 등록본이 모두 저장되었다
  const mine = await (await page.request.get("/api/v1/me/resume")).json();
  expect(mine.data.name).toBe("여정테스트");
  expect(mine.basic_info_complete).toBe(true);
  const apps = await (await page.request.get("/api/v1/me/applications")).json();
  expect(apps[0].status).toBe("prepared");
  expect(apps[0].session_id).toBeTruthy();
});

test("지원 후에는 목록에 '지원 완료', 상세 버튼은 단계에 맞게 '장치 점검으로 이동'이 된다", async () => {
  await page.goto("/jobs");
  const card = page.getByTestId("job-card").filter({ hasText: "백엔드 개발자" });
  await expect(card).toContainText("지원 완료");
  await card.click();
  await expect(page.getByTestId("apply-btn")).toHaveCount(0);
  await page.getByRole("button", { name: "장치 점검으로 이동" }).click();
  await expect(page).toHaveURL(/\/device-check$/);
});

test("장치 점검: 카메라 → 마이크 → 스피커 순서로 통과해야 [면접 시작]이 켜지고 면접 화면으로 간다", async () => {
  await page.goto(`${appUrl}/device-check`);
  const status = (s: string) => page.getByTestId(`step-${s}`);
  const start = page.getByTestId("start-interview");

  await expect(page.getByTestId("camera-preview").locator("video")).toBeVisible();
  await expect(status("camera")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });
  await expect(page.getByTestId("face-status")).toContainText(/\S/);
  await expect(start).toBeDisabled();

  await expect(status("mic")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });   // 가짜 마이크의 비프음이 임계를 넘는다
  await expect(page.getByTestId("mic-meter")).toHaveAttribute("aria-valuenow", "100");

  await expect(status("speaker")).toHaveAttribute("data-status", "checking");
  await expect(page.getByTestId("heard-yes")).toHaveCount(0);                                // 재생하기 전에는 확인 버튼이 없다
  await page.getByTestId("play-guide").click();
  await page.getByTestId("heard-no").click();
  await expect(page.getByTestId("heard-no-hint")).toBeVisible();
  await expect(start).toBeDisabled();                                                        // [안 들려요]는 통과가 아니다
  await page.getByTestId("play-guide").click();
  await page.getByTestId("heard-yes").click();
  await expect(status("speaker")).toHaveAttribute("data-status", "pass");
  await expect(start).toBeEnabled({ timeout: 10_000 });                                      // 서버 저장까지 끝난 뒤에 활성

  // 통과한 카메라 단계를 다시 누르면 이후 단계가 모두 초기화된다
  await status("camera").getByRole("button").click();
  await expect(status("mic")).toHaveAttribute("data-status", "idle");
  await expect(start).toBeDisabled();
  await expect(status("camera")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });
  await expect(status("mic")).toHaveAttribute("data-status", "pass", { timeout: 20_000 });

  // 점검 결과 저장이 실패하면 3단계를 모두 통과했어도 [면접 시작]은 켜지지 않는다 (서버 저장 성공이 활성 조건)
  await page.route("**/api/v1/sessions/*/device-check", (r) => r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "INTERNAL", message: "fail", details: {}, request_id: "r" } }) }));
  await page.getByTestId("play-guide").click();
  await page.getByTestId("heard-yes").click();
  await expect(status("speaker")).toHaveAttribute("data-status", "pass");
  await expect(page.getByRole("button", { name: "점검 결과 다시 저장" })).toBeVisible();
  await expect(start).toBeDisabled();
  await page.unroute("**/api/v1/sessions/*/device-check");
  await page.getByRole("button", { name: "점검 결과 다시 저장" }).click();
  await expect(start).toBeEnabled({ timeout: 10_000 });

  await start.click();
  await expect(page).toHaveURL(/\/interview\/[0-9a-f-]+$/, { timeout: 60_000 });
  await expect(page.getByTestId("start-btn")).toBeVisible();                                 // 면접 시작 게이트

  const stored = await page.evaluate(() => window.sessionStorage.getItem("ai-interview:devices"));
  expect(stored).not.toBeNull();
  const apps = await (await page.request.get("/api/v1/me/applications")).json();
  const state = await (await page.request.get(`/api/v1/sessions/${apps[0].session_id}/state`)).json();
  expect(state.state).toBe("ready");
  expect(errors).toEqual([]);
});

// ── 마이페이지 등록본을 가진 두 번째 지원자 ──
test("등록본이 있으면 기본 선택이 '마이페이지 등록본'(읽기 전용)이고, PDF 추출 결과는 폼에 채워지며 되돌아오면 등록본으로 복원된다", async ({ browser }) => {
  const ctxB = await browser.newContext({ permissions: ["camera", "microphone"] });
  const b = await ctxB.newPage();
  const errs: string[] = [];
  b.on("pageerror", (e) => errs.push(e.message));
  const email = `journey-b-${Date.now()}@corp.local`;
  expect((await b.request.post("/api/v1/auth/register", { data: { name: "등록본", email, password: "Passw0rd!", password_confirm: "Passw0rd!", birth_date: "1998-05-05", gender: "male", phone: "010-2222-3333" } })).status()).toBe(201);
  expect((await b.request.put("/api/v1/me/resume", { data: { name: "등록본지원자", education: [{ school: "마이대학교", major: "소프트웨어" }], skills: ["Kotlin"] } })).ok()).toBe(true);

  await b.goto("/jobs");
  await b.getByTestId("job-card").filter({ hasText: "백엔드 개발자" }).click();
  await b.getByTestId("apply-btn").click();
  const dialog = b.getByRole("dialog", { name: "개인정보 활용 동의" });
  await dialog.getByLabel(/개인정보 수집·이용에 동의/).check();
  await dialog.getByLabel(/녹화·저장 및 AI 평가에 동의/).check();
  await dialog.getByRole("button", { name: "동의하고 계속" }).click();
  await expect(b).toHaveURL(/\/resume$/);

  await expect(b.getByRole("radio", { name: /마이페이지 등록본/ })).toBeChecked();
  await expect(b.getByLabel("성명")).toHaveValue("등록본지원자");
  await expect(b.getByLabel("성명")).toBeDisabled();                  // 읽기 전용 미리보기
  await expect(b.getByTestId("next-btn")).toBeEnabled();

  // PDF 추출 결과(네트워크만 대체)가 폼에 채워진다
  await b.route("**/api/v1/me/resume/upload", (r) => r.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ job_id: "mockjob" }) }));
  await b.route("**/api/v1/resume-jobs/mockjob", (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "done", used_ocr: false, dropped: 0, fell_back: false, data: { name: "추출김", education: [{ school: "추출대학교" }], experience: [{ company: "다온", role: "백엔드" }], skills: ["Java", "Redis"] } }) }));
  await b.getByRole("radio", { name: /PDF 새로 첨부/ }).check();
  await expect(b.getByLabel("성명")).toHaveCount(0);                  // 추출 전에는 폼이 보이지 않는다
  await b.getByTestId("pdf-input").setInputFiles(path.join(__dirname, "fixtures/resume-ko.pdf"));
  await expect(b.getByTestId("extracted-banner")).toBeVisible({ timeout: 15_000 });
  await expect(b.getByLabel("성명")).toHaveValue("추출김");
  await expect(b.getByLabel("학교명 1", { exact: true })).toHaveValue("추출대학교");
  await expect(b.getByLabel("회사명 1", { exact: true })).toHaveValue("다온");
  await expect(b.getByRole("list", { name: "기술 목록" })).toContainText("Redis");
  await expect(b.getByLabel("성명")).toBeEnabled();                    // 추출 결과는 수정 가능

  // 등록본으로 되돌리면 추출 값이 아닌 등록본이 다시 보인다
  await b.getByRole("radio", { name: /마이페이지 등록본/ }).check();
  await expect(b.getByLabel("성명")).toHaveValue("등록본지원자");
  await expect(b.getByLabel("성명")).toBeDisabled();
  await b.getByRole("button", { name: "수정" }).click();
  await b.getByLabel("성명").fill("등록본수정");
  await b.getByTestId("next-btn").click();
  await expect(b).toHaveURL(/\/device-check$/);

  // 이번 지원용 스냅샷에만 수정본이 쓰이고, 마이페이지 등록본은 그대로다 (PRD 10장 #11)
  const apps = await (await b.request.get("/api/v1/me/applications")).json();
  const snap = await (await b.request.get(`/api/v1/applications/${apps[0].application_id}/resume/standard`)).json();
  expect(snap.data.name).toBe("등록본수정");
  expect((await (await b.request.get("/api/v1/me/resume")).json()).data.name).toBe("등록본지원자");
  expect(errs).toEqual([]);
  await ctxB.close();
});
