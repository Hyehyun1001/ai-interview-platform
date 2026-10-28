import { expect, test } from "@playwright/test";
import { login } from "./helpers";

/** 모바일(390px) 폭에서 주요 화면이 가로로 넘치지 않는지 확인한다. 넘치면 어떤 요소가 넘치는지 함께 알려 준다. */
test.use({ viewport: { width: 390, height: 844 } });

async function overflow(page: import("@playwright/test").Page): Promise<string[]> {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    if (document.documentElement.scrollWidth <= vw) return [];
    const bad: string[] = [];
    document.querySelectorAll<HTMLElement>("body *").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > vw + 1 && !el.closest("[data-allow-x-scroll],.overflow-x-auto")) bad.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 50)} (${Math.round(r.right)}px)`);
    });
    return bad.slice(0, 5);
  });
}

const APPLICANT = ["/login", "/jobs", "/jobs?mypage=applications", "/jobs?mypage=resume", "/jobs?mypage=profile"];
const ADMIN = ["/admin", "/admin/jobs", "/admin/applicants", "/admin/calendar", "/admin/history", "/admin/jobs/new"];

test("지원자 화면은 모바일 폭에서 가로로 넘치지 않는다", async ({ page }) => {
  await page.goto("/login");
  expect(await overflow(page), "/login").toEqual([]);
  await login(page, "applicant@corp.local", "applicant");
  for (const url of APPLICANT.slice(1)) {
    await page.goto(url);
    await page.waitForTimeout(500);
    expect(await overflow(page), url).toEqual([]);
  }
  await page.goto("/jobs");
  await page.getByTestId("job-card").first().click();
  await page.waitForTimeout(500);
  expect(await overflow(page), "job detail").toEqual([]);
});

test("담당자 화면은 모바일 폭에서 가로로 넘치지 않는다 (표는 자체 스크롤)", async ({ page }) => {
  await login(page, "hr@corp.local", "recruiter");
  for (const url of ADMIN) {
    await page.goto(url);
    await page.waitForTimeout(600);
    expect(await overflow(page), url).toEqual([]);
  }
  await page.goto("/admin/applicants");
  await page.getByRole("row", { name: /이도윤/ }).getByRole("link", { name: "상세 보기" }).click();
  for (const tab of ["평가 요약", "문답·플레이어", "표준 이력서", "메모"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(500);
    expect(await overflow(page), `detail:${tab}`).toEqual([]);
  }
});
