import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Passw0rd!";

export async function login(page: Page, email: string, role: "applicant" | "recruiter") {
  await page.goto("/login");
  const tab = page.getByRole("tab", { name: role === "applicant" ? /지원자/ : /담당자/ });
  if (await tab.count()) await tab.first().click();
  await page.getByLabel(/이메일/).fill(email);
  await page.getByLabel(/비밀번호/).fill(PASSWORD);
  await page.getByRole("button", { name: /로그인/ }).last().click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));  // 로그인 요청이 끝나기 전에 다른 곳으로 이동하지 않도록
}

const RESUME = { name: "김지원", education: [{ school: "한빛대학교", major: "컴퓨터공학" }], skills: ["Java", "Redis"] };

/**
 * 실제 REST API 로 면접 준비를 끝낸다(프론트의 지원/이력서/장치 점검 화면은 아직 없다): 공고 조회 → 지원 → 이력서 확정 →
 * 세션 생성 → 장치 점검 → 시작(준비·warm-up 완료까지 polling). 이미 한 단계는 건너뛰므로 여러 번 호출해도 같은 세션을 돌려준다.
 */
export async function prepareInterview(page: Page, resumeSource: "manual" | "mypage" = "manual"): Promise<string> {
  const api = page.request;
  const jobs = await (await api.get("/api/v1/jobs")).json();
  const jobId = jobs.items.find((j: { title: string }) => j.title.startsWith("백엔드"))!.id as string;
  const applied = await api.post(`/api/v1/jobs/${jobId}/apply`, { data: { consent: true, consent_version: "2026-01" } });
  const applicationId = applied.ok() ? (await applied.json()).application_id : (await applied.json()).error.details.application_id;
  expect((await api.put(`/api/v1/applications/${applicationId}/resume`, { data: resumeSource === "mypage" ? { source: "mypage" } : { source: "manual", data: RESUME } })).status()).toBeLessThan(500);
  const session = await (await api.post(`/api/v1/applications/${applicationId}/session`)).json();
  const sid = session.session_id as string;
  expect((await api.post(`/api/v1/sessions/${sid}/device-check`, { data: { camera: true, mic: true, speaker: true, devices: {} } })).ok()).toBe(true);
  await expect.poll(async () => (await api.post(`/api/v1/sessions/${sid}/start`)).status(), { timeout: 30_000 }).toBe(200);
  return sid;
}
