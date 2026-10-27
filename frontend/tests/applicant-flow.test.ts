import { describe, expect, it, beforeEach } from "vitest";
import { MicDetector, activeStep, allPassed, dbToMeter, initialStates, isUnlocked, makeChimeWav, readDeviceChoice, readGazeBase, resetFrom, rmsOfSamples, rmsToDb, saveDeviceChoice, saveGazeBase } from "@/features/device-check/device-logic";
import { CATEGORIES, buildJobsHref, continueTarget, formatDeadline, isDeadlinePassed, parseJobsQuery, totalPages } from "@/features/jobs/logic";
import { basicInfoIssues, emptyResumeForm, isBasicInfoComplete, toFormValues, toResumeData, validatePdfFile, type ResumeFormValues } from "@/features/resume/schema";

const form = (over: Partial<ResumeFormValues> = {}): ResumeFormValues => ({ ...emptyResumeForm(), ...over });

describe("이력서 기본 정보 규칙 (성명 + 학력/경력 1건)", () => {
  it("성명이 없거나 학교명·회사명이 모두 비면 미충족", () => {
    expect(isBasicInfoComplete(emptyResumeForm())).toBe(false);
    expect(basicInfoIssues(form({ name: "홍길동" }))).toEqual({ name: false, career: true });
    expect(basicInfoIssues(form({ education: [{ school: "한빛대", major: "", degree: "", start: "", end: "" }] }))).toEqual({ name: true, career: false });
  });
  it("학교명이 비어 있는 학력(전공만)은 1건으로 인정하지 않는다", () => {
    expect(isBasicInfoComplete(form({ name: "홍길동", education: [{ school: " ", major: "컴공", degree: "", start: "", end: "" }] }))).toBe(false);
  });
  it("경력의 회사명만 있어도 충족, 자소서는 필수가 아니다", () => {
    const v = form({ name: "홍길동", education: [], experience: [{ company: "다온", role: "", start: "", end: "", summary: "" }] });
    expect(isBasicInfoComplete(v)).toBe(true);
    expect(v.self_intro).toBe("");
  });
});

describe("이력서 변환", () => {
  it("추출 못 한 필드(null)는 빈 값으로, 빈 행·빈 문자열은 서버로 보내지 않는다", () => {
    const f = toFormValues({ name: null, education: [{ school: "한빛대", major: null }], projects: [{ title: "P", tech_stack: ["Java", "Redis"] }] });
    expect(f.name).toBe("");
    expect(f.projects[0]!.tech_stack).toBe("Java, Redis");
    const out = toResumeData({ ...f, name: " 홍길동 ", education: [...f.education, { school: "", major: "", degree: "", start: "", end: "" }], experience: [{ company: "", role: "", start: "", end: "", summary: "" }], self_intro: "" });
    expect(out.name).toBe("홍길동");
    expect(out.education).toHaveLength(1);
    expect(out.education![0]!.major).toBeNull();
    expect(out.experience).toEqual([]);
    expect(out.self_intro).toBeNull();
    expect(out.projects![0]!.tech_stack).toEqual(["Java", "Redis"]);
  });
  it("왕복 변환해도 값이 보존된다", () => {
    const src = { name: "김지원", education: [{ school: "한빛대학교", major: "컴퓨터공학", degree: "학사", start: "2019.03", end: "2023.02" }], experience: [], projects: [], skills: ["Java"], certifications: [], self_intro: "안녕하세요" };
    const back = toResumeData(toFormValues(src));
    expect(back).toMatchObject({ name: "김지원", skills: ["Java"], self_intro: "안녕하세요" });
    expect(back.education![0]).toMatchObject({ school: "한빛대학교", start: "2019.03" });
  });
});

describe("PDF 1차 검증", () => {
  const f = (name: string, type: string, size = 1000) => ({ name, type, size });
  it("PDF 만 허용하고 문서/이미지는 거부한다", () => {
    expect(validatePdfFile(f("a.pdf", "application/pdf"))).toBeNull();
    expect(validatePdfFile(f("A.PDF", ""))).toBeNull();
    for (const bad of [f("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), f("a.hwp", ""), f("a.png", "image/png"), f("a.pdf", "image/png"), f("a", "application/pdf")])
      expect(validatePdfFile(bad)).toBe("PDF 파일만 업로드할 수 있습니다.");
  });
  it("10MB 초과/빈 파일을 거부한다 (경계 포함)", () => {
    expect(validatePdfFile(f("a.pdf", "application/pdf", 10 * 1024 * 1024))).toBeNull();
    expect(validatePdfFile(f("a.pdf", "application/pdf", 10 * 1024 * 1024 + 1))).toContain("10MB");
    expect(validatePdfFile(f("a.pdf", "application/pdf", 0))).toContain("빈 파일");
  });
});

describe("공고 목록 URL 쿼리", () => {
  const sp = (q: string) => new URLSearchParams(q);
  it("알 수 없는 카테고리와 잘못된 페이지는 기본값으로 되돌린다", () => {
    expect(parseJobsQuery(sp("category=해킹&page=-3&q=%20java%20"))).toEqual({ category: null, q: "java", page: 1 });
    expect(parseJobsQuery(sp("category=개발&page=abc"))).toEqual({ category: "개발", q: "", page: 1 });
    expect(parseJobsQuery(sp("page=3")).page).toBe(3);
  });
  it("href 는 기본값을 생략하고 왕복해도 같다", () => {
    expect(buildJobsHref({})).toBe("/jobs");
    expect(buildJobsHref({ category: "개발", q: " 백엔드 ", page: 2 })).toBe("/jobs?category=%EA%B0%9C%EB%B0%9C&q=%EB%B0%B1%EC%97%94%EB%93%9C&page=2");
    expect(parseJobsQuery(new URL(`http://x${buildJobsHref({ category: "개발", q: "백엔드", page: 2 })}`).searchParams)).toEqual({ category: "개발", q: "백엔드", page: 2 });
    expect(CATEGORIES).toContain("개발");
  });
  it("페이지 수는 최소 1", () => { expect(totalPages(0)).toBe(1); expect(totalPages(12)).toBe(1); expect(totalPages(13)).toBe(2); });
  it("마감 판정", () => {
    const now = new Date("2026-11-01T00:00:00Z");
    expect(isDeadlinePassed("2026-10-31T23:59:59Z", now)).toBe(true);
    expect(isDeadlinePassed("2026-11-01T00:00:01Z", now)).toBe(false);
    expect(isDeadlinePassed(null, now)).toBe(false);
    expect(formatDeadline(null)).toBe("상시 모집");
  });
});

describe("지원 상태별 이어하기 목적지 (UI_SPEC §4.2.2)", () => {
  const base = { application_id: "A1", session_id: "S1", result: null, report_status: null };
  it.each([
    ["applied", "/apply/A1/resume", "이어서 진행하기"],
    ["prepared", "/apply/A1/device-check", "장치 점검으로 이동"],
    ["interviewing", "/interview/S1", "면접 이어하기"],
    ["interview_done", "/interview/S1/waiting", "리포트 생성 중"],
    ["report_ready", "/reports/S1", "리포트 보기"],
  ] as const)("%s", (status, href, label) => { expect(continueTarget({ ...base, status })).toEqual({ href, label }); });
  it("세션이 없는 면접 단계는 안전한 이전 단계로 보낸다", () => {
    expect(continueTarget({ ...base, status: "interviewing", session_id: null }).href).toBe("/apply/A1/device-check");
    expect(continueTarget({ ...base, status: "report_ready", session_id: null }).href).toBe("/apply/A1/resume");
  });
});

describe("장치 점검 단계 규칙", () => {
  it("순서 고정: 앞 단계가 통과해야 다음이 열린다", () => {
    const s = initialStates();
    expect(activeStep(s)).toBe("camera");
    expect(isUnlocked(s, "camera")).toBe(true);
    expect(isUnlocked(s, "mic")).toBe(false);
    s.camera = "pass";
    expect(isUnlocked(s, "mic")).toBe(true);
    expect(isUnlocked(s, "speaker")).toBe(false);
    expect(activeStep(s)).toBe("mic");
  });
  it("모두 통과해야 allPassed, 한 단계를 다시 점검하면 그 뒤 단계도 초기화", () => {
    const all = { camera: "pass", mic: "pass", speaker: "pass" } as const;
    expect(allPassed({ ...all })).toBe(true);
    expect(allPassed({ ...all, speaker: "idle" })).toBe(false);
    expect(resetFrom({ ...all }, "mic")).toEqual({ camera: "pass", mic: "idle", speaker: "idle" });
    expect(resetFrom({ ...all }, "camera")).toEqual(initialStates());
  });
});

describe("마이크 레벨 판정 (-50dBFS 이상 누적 0.5초)", () => {
  it("dB 변환과 미터 범위", () => {
    expect(rmsToDb(1)).toBeCloseTo(0, 5);
    expect(rmsToDb(0.1)).toBeCloseTo(-20, 5);
    expect(rmsToDb(0)).toBeLessThan(-100);
    expect(dbToMeter(-80)).toBe(0); expect(dbToMeter(0)).toBe(1);
    expect(rmsOfSamples([])).toBe(0);
    expect(rmsOfSamples([0.5, -0.5, 0.5, -0.5])).toBeCloseTo(0.5, 6);
  });
  it("임계 이상이 누적 500ms 가 되어야 통과한다 (끊겨도 누적, 임계 미만은 불가)", () => {
    const d = new MicDetector();
    expect(d.feed(-40, 200).passed).toBe(false);
    expect(d.feed(-70, 300).passed).toBe(false);   // 무음 구간은 누적하지 않는다
    expect(d.feed(-40, 299).passed).toBe(false);   // 499ms
    expect(d.feed(-40, 1).passed).toBe(true);      // 500ms
    const quiet = new MicDetector();
    for (let i = 0; i < 100; i++) expect(quiet.feed(-60, 100).passed).toBe(false);
  });
  it("5초 무음이면 안내하고, 소리가 들어오면 해제된다", () => {
    const d = new MicDetector();
    expect(d.feed(-70, 4900).silent).toBe(false);
    expect(d.feed(-70, 200).silent).toBe(true);
    expect(d.feed(-30, 100).silent).toBe(false);
  });
});

describe("sessionStorage 보관", () => {
  beforeEach(() => window.sessionStorage.clear());
  it("선택 장치 왕복 / 손상된 값은 빈 선택", () => {
    saveDeviceChoice({ video: "v1", audio: "a1" });
    expect(readDeviceChoice()).toEqual({ video: "v1", audio: "a1", output: undefined });
    window.sessionStorage.setItem("ai-interview:devices", "{broken");
    expect(readDeviceChoice()).toEqual({});
  });
  it("정면 보정값은 세션별이며 숫자가 아니면 버린다", () => {
    saveGazeBase("S1", { yaw: 1, pitch: 2, irisX: 0.5, irisY: 0.4 });
    expect(readGazeBase("S1")).toEqual({ yaw: 1, pitch: 2, irisX: 0.5, irisY: 0.4 });
    expect(readGazeBase("S2")).toBeNull();
    window.sessionStorage.setItem("ai-interview:gaze-base:S3", JSON.stringify({ yaw: "x", pitch: 1, irisX: 1, irisY: 1 }));
    expect(readGazeBase("S3")).toBeNull();
  });
});

describe("안내 음성 WAV", () => {
  it("유효한 RIFF/WAVE 헤더와 길이", () => {
    const w = makeChimeWav(22050);
    const tag = (o: number) => String.fromCharCode(...w.slice(o, o + 4));
    expect(tag(0)).toBe("RIFF"); expect(tag(8)).toBe("WAVE"); expect(tag(36)).toBe("data");
    const dv = new DataView(w.buffer);
    expect(dv.getUint32(40, true)).toBe(w.length - 44);
    expect(w.length).toBeGreaterThan(44 + 22050);  // 1초 이상
    expect(w.slice(44).some((b) => b !== 0)).toBe(true);
  });
});
