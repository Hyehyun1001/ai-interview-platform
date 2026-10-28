import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { PASSWORD, login } from "./helpers";

/**
 * 가입 직후 이력서 팝업(APP-01b) · 마이페이지(APP-04) · 담당자 메모/템플릿/미리보기 · 코딩테스트(샌드박스 + 코드 꼬리질문).
 * 가짜 엔진 스택이지만 샌드박스는 사전 빌드된 도커 이미지가 있으면 **실제 컨테이너**에서 코드를 실행한다(dev_fake_stack.py 가 로그에 어느 쪽인지 남긴다).
 */
test.describe.configure({ mode: "serial" });

const stamp = Date.now();
const signupData = (tag: string) => ({ name: `가입${tag}`, email: `su-${tag}-${stamp}@corp.local`, password: PASSWORD, birth: "1998/05/05", phone: "010-5555-1234" });

async function signUp(page: Page, d: ReturnType<typeof signupData>) {
  await page.goto("/login?signup=1");
  const dlg = page.getByRole("dialog", { name: "회원가입" });
  await expect(dlg).toBeVisible();
  await dlg.getByLabel("이름 *").fill(d.name);
  await dlg.getByLabel("이메일 *").fill(d.email);
  await dlg.getByLabel("비밀번호 *", { exact: true }).fill(d.password);
  await dlg.getByLabel("비밀번호 확인 *").fill(d.password);
  await dlg.getByLabel("생년월일 *").fill(d.birth);
  await dlg.getByLabel("남", { exact: true }).check();
  await dlg.getByLabel("연락처 *").fill(d.phone);
  await dlg.getByRole("button", { name: "가입하기" }).click();
}

test("회원가입 모달: 검증 오류와 중복 이메일을 보여 주고, 성공하면 환영 팝업이 열린다 → 직접 작성으로 이력서 등록", async ({ page }) => {
  const d = signupData("a");
  await page.goto("/login?signup=1");
  const dlg = page.getByRole("dialog", { name: "회원가입" });
  await dlg.getByRole("button", { name: "가입하기" }).click();
  await expect(dlg.getByText("이름을 입력하세요")).toBeVisible();
  // 키보드로 한 글자씩 입력해도 포커스가 다른 필드로 튀지 않는다 (모달이 렌더마다 포커스를 첫 요소로 되돌리던 회귀 방지)
  const pwField = dlg.getByLabel("비밀번호 *", { exact: true });
  await pwField.click();
  await page.keyboard.type("abcdefgh");
  await expect(pwField).toHaveValue("abcdefgh");
  await expect(dlg.getByLabel("이름 *")).toHaveValue("");
  await dlg.getByLabel("비밀번호 확인 *").fill("different1!");
  await dlg.getByRole("button", { name: "가입하기" }).click();
  await expect(dlg.getByText("영문, 숫자, 특수문자를 모두 포함해야 합니다")).toBeVisible();
  await expect(dlg.getByText("비밀번호가 일치하지 않습니다")).toBeVisible();

  // 이미 가입된 이메일
  await dlg.getByLabel("이름 *").fill("중복");
  await dlg.getByLabel("이메일 *").fill("applicant@corp.local");
  await dlg.getByLabel("비밀번호 *", { exact: true }).fill(d.password);
  await dlg.getByLabel("비밀번호 확인 *").fill(d.password);
  await dlg.getByLabel("생년월일 *").fill(d.birth);
  await dlg.getByLabel("남", { exact: true }).check();
  await dlg.getByLabel("연락처 *").fill(d.phone);
  await dlg.getByRole("button", { name: "가입하기" }).click();
  await expect(dlg.getByText("이미 가입된 이메일입니다")).toBeVisible();

  await dlg.getByLabel("이메일 *").fill(d.email);
  await dlg.getByRole("button", { name: "가입하기" }).click();
  await expect(page).toHaveURL(/\/jobs\?welcome=1/);
  const welcome = page.getByRole("dialog", { name: "가입을 환영합니다!" });
  await expect(welcome).toBeVisible();

  // 기본 정보가 비어 있으면 저장할 수 없다
  await welcome.getByRole("button", { name: "직접 작성하기" }).click();
  await expect(welcome.getByTestId("resume-save")).toBeDisabled();
  await welcome.getByLabel("성명").fill(d.name);
  await expect(welcome.getByTestId("resume-save")).toBeDisabled();             // 성명만으로는 부족
  await welcome.getByLabel("학교명 1", { exact: true }).fill("한빛대학교");
  await expect(welcome.getByTestId("resume-save")).toBeEnabled();
  await welcome.getByTestId("resume-save").click();
  await expect(welcome).toBeHidden();
  await expect(page).toHaveURL(/\/jobs$/);                                     // ?welcome=1 제거
  const me = await (await page.request.get("/api/v1/me/resume")).json();
  expect(me.data.name).toBe(d.name);
  expect(me.basic_info_complete).toBe(true);
  expect(me.source).toBe("manual");
  await page.goto("/jobs?welcome=1");                                          // 이미 등록한 사용자는 URL 로 다시 열어도 팝업이 뜨지 않는다
  await expect(page.getByTestId("job-card").first()).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("환영 팝업 Skip: dismiss 가 기록되고 이후에는 GNB 아래 배너로만 안내한다 → 배너로 마이페이지 이력서 탭 이동", async ({ page }) => {
  const d = signupData("b");
  await signUp(page, d);
  const welcome = page.getByRole("dialog", { name: "가입을 환영합니다!" });
  await expect(welcome).toBeVisible();
  await expect(page.getByTestId("resume-banner")).toHaveCount(0);              // 팝업을 보는 동안에는 배너가 없다
  await welcome.getByTestId("welcome-skip").click();
  await expect(welcome).toBeHidden();
  await expect(page.getByTestId("resume-banner")).toBeVisible();
  expect((await (await page.request.get("/api/v1/me")).json()).resume_popup_dismissed_at).toBeTruthy();
  await page.goto("/jobs?welcome=1");                                          // 다시 열어도 (dismiss 와 무관하게 URL 이 명시했으므로) 팝업은 열리되 Skip 가능
  await page.getByRole("dialog").getByTestId("welcome-skip").click();
  await page.getByTestId("resume-banner").getByRole("link", { name: /지금 등록하기/ }).click();
  await expect(page).toHaveURL(/mypage=resume/);
  await expect(page.getByRole("dialog", { name: /마이페이지/ })).toBeVisible();
  await expect(page.getByTestId("resume-empty")).toBeVisible();
  await expect(page.getByTestId("resume-banner")).toHaveCount(0);              // 마이페이지 패널이 열려 있으면 숨긴다
});

test.describe("마이페이지", () => {
  const d = signupData("c");
  let ctx: BrowserContext;
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    ctx = await browser.newContext();
    page = await ctx.newPage();
    const reg = await page.request.post("/api/v1/auth/register", { data: { name: d.name, email: d.email, password: d.password, password_confirm: d.password, birth_date: "1998-05-05", gender: "male", phone: d.phone } });
    expect(reg.status()).toBe(201);
  });
  test.afterAll(async () => { await ctx.close(); });

  test("사람 아이콘을 누르면 오른쪽 패널로 열리고, ESC·배경 클릭으로 닫히며 포커스가 돌아온다 / 로그인 정보가 표시된다", async () => {
    await page.goto("/jobs");
    await expect(page.getByRole("link", { name: "마이페이지" })).toHaveCount(0);                // 로고 옆 마이페이지 링크는 없다
    const btn = page.getByTestId("account-btn");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await btn.click();
    const dlg = page.getByRole("dialog", { name: /마이페이지/ });
    await expect(dlg).toBeVisible();
    await expect(page).toHaveURL(/\/jobs\?mypage=applications/);
    await expect(page.getByTestId("drawer-user")).toContainText(d.email);
    await expect(dlg).toBeFocused();                                                            // 첫 포커스는 패널 자체
    for (let i = 0; i < 25; i++) {                                                              // Tab 을 아무리 눌러도 패널 밖으로 나가지 않는다 (focus trap)
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]'))).toBe(true);
    }
    await expect(page.getByRole("tab", { name: /일정/ })).toHaveCount(0);                        // 비활성 '일정' 탭은 없앴다
    const box = await dlg.boundingBox();
    const vw = page.viewportSize()!.width;
    expect(box!.x + box!.width).toBeGreaterThan(vw - 2);                                        // 오른쪽에 붙는다
    expect(box!.x).toBeGreaterThan(vw * 0.3);                                                   // 화면 전체를 덮지 않는다(데스크톱)
    await page.keyboard.press("Escape");
    await expect(dlg).toBeHidden();
    await expect(page).not.toHaveURL(/mypage=/);
    await expect(btn).toBeFocused();
    await btn.click();
    await expect(dlg).toBeVisible();
    await page.mouse.click(20, 300);                                                            // 배경(왼쪽 어두운 영역)
    await expect(dlg).toBeHidden();
    await page.goto("/jobs?mypage=profile");                                                    // 딥링크·새로고침으로도 열린다
    await expect(page.getByRole("tab", { name: "프로필 정보" })).toHaveAttribute("aria-selected", "true");
  });

  test("탭이 URL 에 유지되고, 지원 현황이 없으면 빈 상태를 보여 준다", async () => {
    await page.goto("/mypage");                                                   // 예전 주소는 패널이 열린 공고 목록으로 보낸다
    await expect(page).toHaveURL(/\/jobs\?mypage=applications/);
    await expect(page.getByRole("tab", { name: "지원 현황" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("아직 지원한 공고가 없어요")).toBeVisible();
    await page.getByRole("tab", { name: "프로필 정보" }).click();
    await expect(page).toHaveURL(/mypage=profile/);
    await page.reload();
    await expect(page.getByRole("tab", { name: "프로필 정보" })).toHaveAttribute("aria-selected", "true");
  });

  test("지원 현황: 지원한 공고가 상태와 다음 액션과 함께 나온다", async () => {
    const jobs = await (await page.request.get("/api/v1/jobs")).json();
    const job = jobs.items.find((j: { title: string }) => j.title.startsWith("백엔드"));
    const ap = await page.request.post(`/api/v1/jobs/${job.id}/apply`, { data: { consent: true, consent_version: "2026-01" } });
    expect(ap.ok()).toBe(true);
    await page.goto("/jobs?mypage=applications");
    const row = page.getByTestId("application-item").filter({ hasText: "백엔드 개발자" });
    await expect(row).toContainText("이력서 제출 대기");
    await row.getByRole("link", { name: "이어서 진행하기" }).click();
    await expect(page).toHaveURL(/\/apply\/.+\/resume/);
  });

  test("이력서 탭: 미등록 안내 → PDF/직접 작성 선택 → 저장하면 등록본이 생기고, 지원 건 스냅샷은 바뀌지 않는다", async () => {
    await page.goto("/jobs?mypage=resume");
    await expect(page.getByTestId("resume-empty")).toBeVisible();
    await page.getByRole("button", { name: "직접 작성하기" }).click();
    await page.getByLabel("성명").fill("마이페이지이름");
    await page.getByLabel("학교명 1", { exact: true }).fill("한빛대학교");
    await page.getByTestId("resume-save").click();
    await expect(page.getByText("● 등록됨")).toBeVisible();
    const saved = await (await page.request.get("/api/v1/me/resume")).json();
    expect(saved.data.name).toBe("마이페이지이름");
    // 수정 → 저장
    await page.getByLabel("성명").fill("수정된이름");
    await page.getByTestId("resume-save").click();
    await expect.poll(async () => ((await (await page.request.get("/api/v1/me/resume")).json()).data.name)).toBe("수정된이름");
  });

  test("PDF 교체: 추출 결과는 폼에만 채워지고 [저장] 전에는 등록본이 바뀌지 않는다 (PRD 10장 #11)", async () => {
    await page.route("**/api/v1/me/resume/upload", (r) => r.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ job_id: "mockjob" }) }));
    await page.route("**/api/v1/resume-jobs/mockjob", (r) => r.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ status: "done", data: { name: "PDF에서추출", education: [{ school: "추출대학교" }] }, fell_back: false, used_ocr: false, dropped: [] }) }));
    await page.goto("/jobs?mypage=resume");
    await page.getByRole("button", { name: "PDF 교체" }).click();
    await page.getByTestId("pdf-input").setInputFiles({ name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 x") });
    await expect(page.getByTestId("extracted-banner")).toBeVisible();
    await expect(page.getByLabel("성명")).toHaveValue("PDF에서추출");
    expect((await (await page.request.get("/api/v1/me/resume")).json()).data.name).toBe("수정된이름");   // 아직 저장 전
    await page.getByTestId("resume-save").click();
    await expect.poll(async () => ((await (await page.request.get("/api/v1/me/resume")).json()).data.name)).toBe("PDF에서추출");
    await page.unroute("**/api/v1/me/resume/upload");
    await page.unroute("**/api/v1/resume-jobs/mockjob");
  });

  test("프로필: 이름·연락처 수정, 비밀번호 변경(현재 비밀번호 불일치 오류)", async () => {
    await page.goto("/jobs?mypage=profile");
    await expect(page.getByText("1998-05-05 · 남")).toBeVisible();
    await page.getByLabel("이름", { exact: true }).fill("새이름");
    await page.getByLabel("연락처").fill("010-9999-8888");
    await page.getByRole("button", { name: "저장", exact: true }).first().click();
    await expect.poll(async () => (await (await page.request.get("/api/v1/me")).json()).name).toBe("새이름");
    expect((await (await page.request.get("/api/v1/me")).json()).phone).toBe("010-9999-8888");

    await page.getByLabel("현재 비밀번호").fill("Wrong123!");
    await page.getByLabel("새 비밀번호", { exact: true }).fill("NewPassw0rd!");
    await page.getByLabel("새 비밀번호 확인").fill("NewPassw0rd!");
    await page.getByRole("button", { name: "비밀번호 변경" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "현재 비밀번호가 일치하지 않습니다" })).toBeVisible();
    await page.getByLabel("현재 비밀번호").fill(PASSWORD);
    await page.getByRole("button", { name: "비밀번호 변경" }).click();
    await expect(page.getByLabel("현재 비밀번호")).toHaveValue("");
    const relog = await ctx.request.post("/api/v1/auth/login", { data: { email: d.email, password: "NewPassw0rd!", role: "applicant" } });
    expect(relog.status()).toBe(200);
  });

  test("패널 하단의 로그아웃은 세션을 끊고 로그인 화면으로 보낸다", async ({ browser }) => {
    const c2 = await browser.newContext();
    const p2 = await c2.newPage();
    await p2.request.post("/api/v1/auth/login", { data: { email: d.email, password: "NewPassw0rd!", role: "applicant" } });
    await p2.goto("/jobs?mypage=applications");
    await p2.getByTestId("logout-btn").click();
    await expect(p2).toHaveURL(/\/login/);
    expect((await p2.request.get("/api/v1/me")).status()).toBe(401);
    await c2.close();
  });

  test("회원 탈퇴: 틀린 비밀번호는 거부, 맞으면 계정·데이터가 삭제되고 다시 로그인할 수 없다", async () => {
    await page.goto("/jobs?mypage=profile");
    await page.getByTestId("delete-account").click();
    const dlg = page.getByRole("dialog", { name: "정말 삭제할까요?" });
    await dlg.getByLabel("비밀번호").fill("Wrong123!");
    await dlg.getByRole("button", { name: "삭제", exact: true }).click();
    await expect(dlg.getByRole("alert")).toContainText("비밀번호가 일치하지 않습니다");
    expect((await page.request.get("/api/v1/me")).status()).toBe(200);          // 아직 계정이 있다
    await dlg.getByLabel("비밀번호").fill("NewPassw0rd!");
    await dlg.getByRole("button", { name: "삭제", exact: true }).click();
    await expect(page).toHaveURL(/\/login/);
    const again = await page.request.post("/api/v1/auth/login", { data: { email: d.email, password: "NewPassw0rd!", role: "applicant" } });
    expect(again.status()).toBe(401);
  });
});

test.describe("담당자: 템플릿 · 미리보기 · 메모", () => {
  const QUESTIONS = Array.from({ length: 10 }, (_, i) => ({ text: `템플릿 질문 ${i + 1}번을 설명해 주세요`, category: "기술" }));
  let tplJobId = "", draftJobId = "";

  test.beforeEach(async ({ page }) => { await login(page, "hr@corp.local", "recruiter"); });

  test("게시하면서 템플릿으로 저장 → 새 공고에서 템플릿을 불러와 덮어쓰기 → 미리보기(읽기 전용)", async ({ page }) => {
    const deadline = new Date(Date.now() + 10 * 86400_000).toISOString();
    const a = await (await page.request.post("/api/v1/admin/jobs", { data: { title: "템플릿 원본 공고", job_category: "개발", headcount: 1, deadline_at: deadline, duties: "서버 개발", requirements: "Java 경험" } })).json();
    tplJobId = a.id;
    expect((await page.request.put(`/api/v1/admin/jobs/${a.id}/questions`, { data: { items: QUESTIONS } })).ok()).toBe(true);
    await page.request.put(`/api/v1/admin/jobs/${a.id}/followup-rules`, { data: { max_followups: 1, trigger_ambiguous: true, trigger_contradiction: false, trigger_stt_unclear: true, guardrail_strict: true } });

    await page.goto(`/admin/jobs/${a.id}/edit?step=4`);
    await page.getByTestId("save-template").check();
    await page.getByTestId("publish-btn").click();                              // 이름 없이 게시하려 하면 막는다
    await expect(page.getByText("템플릿 이름을 입력해 주세요")).toBeVisible();
    await page.getByTestId("template-name").fill("백엔드 기본 세트");
    await page.getByTestId("publish-btn").click();
    await expect(page).toHaveURL(/\/admin\/jobs$/, { timeout: 15_000 });
    const tpls = await (await page.request.get("/api/v1/admin/job-templates")).json();
    expect(tpls.map((t: { name: string }) => t.name)).toContain("백엔드 기본 세트");
    const list = await (await page.request.get("/api/v1/admin/jobs")).json();
    expect(list.items.some((j: { title: string }) => j.title === "템플릿 원본 공고")).toBe(true);
    expect(list.items.filter((j: { title: string }) => j.title === "템플릿 원본 공고")).toHaveLength(1);   // 템플릿 행이 목록에 섞이지 않는다

    const b = await (await page.request.post("/api/v1/admin/jobs", { data: { title: "새 공고 (제목만)" } })).json();
    draftJobId = b.id;
    await page.goto(`/admin/jobs/${b.id}/edit`);
    await page.getByTestId("template-load").click();
    await page.getByRole("radio", { name: /백엔드 기본 세트/ }).check();
    page.once("dialog", (dlg) => void dlg.accept());                              // 덮어쓰기 확인
    await page.getByTestId("template-apply").click();
    await expect(page.getByText("템플릿을 불러왔어요")).toBeVisible();
    const after = await (await page.request.get(`/api/v1/admin/jobs/${b.id}`)).json();
    expect(after.title).toBe("템플릿 원본 공고");
    expect(after.questions).toHaveLength(10);
    expect(after.followup_rules.trigger_contradiction).toBe(false);
    expect(after.status).toBe("draft");

    // 미리보기: 지원자 시점, 읽기 전용
    await page.goto(`/admin/jobs/${b.id}/preview`);
    await expect(page.getByTestId("preview-banner")).toBeVisible();
    await expect(page.getByRole("heading", { name: "템플릿 원본 공고" })).toBeVisible();
    await expect(page.getByRole("button", { name: /지원하기/ })).toBeDisabled();
  });

  test("코딩테스트 토글: 실행 환경이 켜져 있으면 선택할 수 있다", async ({ page }) => {
    await page.goto(`/admin/jobs/${draftJobId}/edit?step=2`);
    const toggle = page.getByTestId("coding-toggle");
    await expect(toggle).toBeEnabled();
    expect((await (await page.request.get("/api/v1/admin/system/metrics")).json()).sandbox_enabled).toBe(true);
  });

  test("지원자 상세 메모 탭: 작성하면 타임라인에 쌓이고, 다른 지원자의 메모와 섞이지 않는다", async ({ page }) => {
    await page.goto("/admin");
    await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
    await page.getByRole("tab", { name: "메모" }).click();
    await expect(page.getByText("아직 메모가 없어요")).toBeVisible();
    await page.getByLabel(/내부 메모/).fill("기술 면접 일정을 잡아 주세요.");
    await page.getByTestId("note-submit").click();
    await expect(page.getByRole("list", { name: "메모 타임라인" })).toContainText("기술 면접 일정을 잡아 주세요.");
    await expect(page.getByRole("list", { name: "메모 타임라인" })).toContainText("박담당 (나)");
    await page.reload();
    await page.getByRole("tab", { name: "메모" }).click();
    await expect(page.getByRole("list", { name: "메모 타임라인" })).toContainText("기술 면접 일정을 잡아 주세요.");

    await page.goto("/admin");
    await page.getByRole("row", { name: /최서연/ }).getByRole("link", { name: "상세 보기" }).click();
    await page.getByRole("tab", { name: "메모" }).click();
    await expect(page.getByText("아직 메모가 없어요")).toBeVisible();
  });
});

// ── 코딩테스트 ───────────────────────────────────────────────────────────────
const SOLUTIONS: Record<string, string> = {
  "두 수의 합": "n, t = map(int, input().split())\na = list(map(int, input().split()))\nseen = {}\nfor i, x in enumerate(a):\n    if t - x in seen:\n        print(seen[t - x], i)\n        break\n    seen[x] = i\n",
  "올바른 괄호": "s = input().strip()\nst = []\npair = {')': '(', ']': '[', '}': '{'}\nok = True\nfor c in s:\n    if c in '([{':\n        st.append(c)\n    elif not st or st.pop() != pair[c]:\n        ok = False\n        break\nprint('YES' if ok and not st else 'NO')\n",
  "가장 많이 나온 단어": "input()\nfrom collections import Counter\nc = Counter(input().split())\nbest = min(c.items(), key=lambda kv: (-kv[1], kv[0]))\nprint(best[0], best[1])\n",
};

async function setCode(page: Page, code: string) {
  // Monaco 는 자동 들여쓰기·괄호 닫기 때문에 키보드 입력이 코드를 바꾼다 — 모델에 직접 넣는다.
  await page.waitForFunction(() => (window as unknown as { monaco?: { editor: { getModels(): unknown[] } } }).monaco?.editor.getModels().length);
  await page.evaluate((c) => (window as unknown as { monaco: { editor: { getModels(): { setValue(v: string): void }[] } } }).monaco.editor.getModels()[0]!.setValue(c), code);
}

test.describe("코딩테스트", () => {
  const d = signupData("code");
  let ctx: BrowserContext;
  let page: Page;
  let sid = "";
  test.beforeAll(async ({ browser }) => {
    ctx = await browser.newContext({ permissions: ["camera", "microphone"] });
    page = await ctx.newPage();
    const reg = await page.request.post("/api/v1/auth/register", { data: { name: "코딩지원자", email: d.email, password: d.password, password_confirm: d.password, birth_date: "1998-05-05", gender: "male", phone: d.phone } });
    expect(reg.status()).toBe(201);
  });
  test.afterAll(async () => { await ctx.close(); });

  test("코딩테스트가 켜진 공고로 면접 준비 → 질문이 끝나면 코딩 탭이 열린다", async () => {
    const api = page.request;
    const jobs = await (await api.get("/api/v1/jobs")).json();
    const job = jobs.items.find((j: { title: string }) => j.title.startsWith("알고리즘"));
    expect(job.coding_test_enabled).toBe(true);
    const applied = await (await api.post(`/api/v1/jobs/${job.id}/apply`, { data: { consent: true, consent_version: "2026-01" } })).json();
    await api.put(`/api/v1/applications/${applied.application_id}/resume`, { data: { source: "manual", data: { name: "코딩지원자", education: [{ school: "한빛대학교", major: "컴퓨터공학" }] } } });
    sid = (await (await api.post(`/api/v1/applications/${applied.application_id}/session`)).json()).session_id;
    await api.post(`/api/v1/sessions/${sid}/device-check`, { data: { camera: true, mic: true, speaker: true, devices: {} } });
    let last = "";
    for (const until = Date.now() + 40_000; Date.now() < until;) {
      const r = await api.post(`/api/v1/sessions/${sid}/start`);
      last = `${r.status()} ${await r.text()}`;
      if (r.status() === 200) break;
      await page.waitForTimeout(1000);
    }
    expect(last, "start 응답").toMatch(/^200 /);
    // 코딩 단계 전에는 문제를 줄 수 없다
    const early = await api.get(`/api/v1/sessions/${sid}/code/problem`);
    expect(early.status()).toBe(409);

    await page.goto(`/interview/${sid}`);
    await page.getByTestId("start-btn").click();
    // 질문 수와 꼬리질문 여부에 의존하지 않도록: 답변할 수 있을 때마다 답하고, 코딩 탭이 열릴 때까지 반복한다
    const coding = page.getByTestId("coding-pane");
    const give = page.getByTestId("answer-done");
    const until = Date.now() + 90_000;
    while (!(await coding.isVisible()) && Date.now() < until) {
      if (await give.isEnabled().catch(() => false)) {
        await page.waitForTimeout(2500);                                       // 서버의 최소 답변 길이(오디오)를 채운다
        await give.click({ timeout: 2000 }).catch(() => undefined);
        await page.waitForTimeout(800);
      } else await page.waitForTimeout(300);
    }
    await expect(page.getByTestId("coding-pane")).toBeVisible({ timeout: 40_000 });
    await expect(page.getByTestId("problem-title")).toBeVisible();
    await expect(page.getByTestId("coding-timer")).toContainText("남은 시간");
  });

  test("샘플 실행(오답 → 정답) → 제출 확인 → 채점 → 코드 꼬리질문(채팅) 답변 → 종료", async () => {
    const title = (await page.getByTestId("problem-title").textContent())!.trim();
    expect(Object.keys(SOLUTIONS)).toContain(title);

    await setCode(page, 'print("WRONG")\n');
    await page.getByTestId("run-btn").click();
    await expect(page.getByTestId("run-result")).toContainText("WA 오답", { timeout: 30_000 });
    await setCode(page, SOLUTIONS[title]!);
    await page.getByTestId("run-btn").click();
    await expect(page.getByTestId("run-result")).toContainText("AC 정답", { timeout: 30_000 });
    await expect(page.getByTestId("case-row")).toHaveCount(2);

    await page.getByTestId("submit-btn").click();
    await page.getByTestId("submit-confirm").click();
    await expect(page.getByTestId("final-verdict")).toContainText("AC 정답", { timeout: 60_000 });
    await expect(page.getByTestId("submit-btn")).toBeDisabled();                 // 제출은 한 번만
    await expect(page.getByTestId("case-row").filter({ hasText: "비공개" }).first()).toBeVisible();
    const res = await (await page.request.get(`/api/v1/sessions/${sid}/code/result`)).json();
    expect(res.verdict).toBe("AC");
    expect(res.source_code).toBeNull();                                         // 지원자 응답에는 코드를 되돌려주지 않는다

    // 코드 꼬리질문 (텍스트 채팅)
    const chat = page.getByTestId("followup-chat");
    await expect(chat).toContainText("시간 복잡도", { timeout: 20_000 });
    await chat.getByTestId("followup-input").fill("해시맵으로 한 번만 순회해서 O(n) 입니다.");
    await chat.getByTestId("followup-send").click();
    await expect(chat.locator('[data-role="me"]')).toContainText("O(n)");
    await expect(chat.getByTestId("followup-input")).toHaveCount(0);

    await page.getByTestId("finish-coding").click();
    await expect(page).toHaveURL(new RegExp(`/interview/${sid}/waiting`), { timeout: 20_000 });
  });

  test("담당자는 제출 코드와 정적 분석을 볼 수 있고, 꼬리질문 답변이 기록되어 있다", async ({ browser }) => {
    const hr = await browser.newContext();
    const p = await hr.newPage();
    await login(p, "hr@corp.local", "recruiter");
    const r = await (await p.request.get(`/api/v1/sessions/${sid}/code/result`)).json();
    expect(r.verdict).toBe("AC");
    expect(r.source_code).toContain("print");
    expect(r.static_analysis.tool).toBeTruthy();
    await hr.close();
    const done = await (await page.request.get("/api/v1/me/applications")).json();
    expect(["interview_done", "report_ready"]).toContain(done.find((a: { session_id: string }) => a.session_id === sid).status);
  });
});

// ── 담당자 지원자 상세 탭 (평가 요약 · 표준 이력서 · 제출 코드) ──────────────────────
test.describe("담당자 상세 탭", () => {
  test.beforeEach(async ({ page }) => { await login(page, "hr@corp.local", "recruiter"); await page.goto("/admin"); });

  test("평가 요약이 기본 탭이고 점수·가중치·강점/개선점·시선·히트맵을 보여 준다 (탭은 URL 에 유지)", async ({ page }) => {
    await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
    await expect(page.getByRole("tab", { name: "평가 요약" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("summary-text")).toContainText("결제 모듈 경험");
    const table = page.getByTestId("criteria-table");
    for (const l of ["개념 이해도", "논리성", "전달력", "태도", "직무 전문성"]) await expect(table).toContainText(l);
    await expect(page.getByText("강점 TOP3")).toBeVisible();
    await expect(page.getByText("정량적 성과 제시")).toBeVisible();
    await expect(page.getByText("협업 경험 구체화")).toBeVisible();
    await expect(page.getByTestId("gaze-card")).toContainText("4.0%");
    await expect(page.getByTestId("heatmap")).toContainText("개념 이해도");
    await expect(page.getByRole("tab", { name: "제출 코드" })).toHaveCount(0);              // 코딩테스트가 없는 공고는 탭 숨김
    await page.getByRole("tab", { name: "표준 이력서" }).click();
    await expect(page).toHaveURL(/tab=resume/);
    await page.reload();
    await expect(page.getByRole("tab", { name: "표준 이력서" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("이력서를 찾을 수 없어요")).toBeVisible();                   // 시드 지원자는 이력서 스냅샷이 없다
  });

  test("리포트 생성 중인 지원자는 요약 탭이 대기 상태를 보여 준다", async ({ page }) => {
    await page.getByRole("row", { name: /정하늘/ }).getByRole("link", { name: "상세 보기" }).click();
    await expect(page.getByTestId("summary-pending")).toBeVisible();
  });

  test("코딩테스트를 제출한 지원자: 표준 이력서와 제출 코드(코드·판정·케이스·정적 분석)를 볼 수 있다", async ({ page }) => {
    const list = await (await page.request.get("/api/v1/admin/applications?limit=50")).json();
    const mine = list.items.find((a: { name: string }) => a.name === "코딩지원자");
    expect(mine, "코딩 지원자가 담당자 목록에 있어야 한다").toBeTruthy();
    await page.goto(`/admin/applications/${mine.application_id}?tab=resume`);
    const resume = page.getByTestId("resume-tab");
    await expect(resume).toContainText("코딩지원자");
    await expect(resume).toContainText("한빛대학교");
    await expect(resume).toContainText("읽기 전용");

    await page.getByRole("tab", { name: "제출 코드" }).click();
    await expect(page.getByTestId("code-verdict")).toContainText("AC 정답", { timeout: 15_000 });
    await expect(page.getByTestId("code-case").first()).toBeVisible();
    await expect(page.getByTestId("static-analysis")).toContainText("코드 줄 수");
    await page.waitForFunction(() => (window as unknown as { monaco?: { editor: { getModels(): { getValue(): string }[] } } }).monaco?.editor.getModels().some((m) => m.getValue().includes("print")));
    // 리포트가 아직 생성되지 않은 지원자의 요약 탭은 대기 상태다 (페이크 스택에는 리포트 워커가 없다)
    await page.getByRole("tab", { name: "평가 요약" }).click();
    await expect(page.getByTestId("summary-pending").or(page.getByText("평가 요약이 없어요"))).toBeVisible();
  });
});
