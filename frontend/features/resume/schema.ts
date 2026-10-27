import type { components } from "@/types/api";

/**
 * 이력서 폼 스키마·검증·변환 (UI_SPEC §4.3.2). 기본 정보 규칙이 바뀌면 이 파일만 고친다.
 * 판정의 기준은 서버(`basic_info_complete`, `422 BASIC_INFO_REQUIRED`)이고, 여기 검증은 UX 보조용이다.
 */
export type ResumeData = components["schemas"]["ResumeSchema"];

export interface EducationRow { school: string; major: string; degree: string; start: string; end: string }
export interface ExperienceRow { company: string; role: string; start: string; end: string; summary: string }
export interface ProjectRow { title: string; role: string; period: string; tech_stack: string; description: string }
export interface ResumeFormValues {
  name: string;
  education: EducationRow[];
  experience: ExperienceRow[];
  projects: ProjectRow[];
  skills: string[];
  certifications: string[];
  self_intro: string;
}

export const MAX_PDF_BYTES = 10 * 1024 * 1024;
export const PDF_ONLY_MESSAGE = "PDF 파일만 업로드할 수 있습니다.";
export const PDF_SIZE_MESSAGE = "10MB 이하의 PDF만 업로드할 수 있습니다.";

export const emptyResumeForm = (): ResumeFormValues => ({
  name: "", education: [{ school: "", major: "", degree: "", start: "", end: "" }], experience: [], projects: [], skills: [], certifications: [], self_intro: "",
});

const str = (v: string | null | undefined): string => v ?? "";
const orNull = (v: string): string | null => (v.trim() === "" ? null : v.trim());

/** 서버 → 폼. 추출하지 못한 필드(null)는 빈 값으로 둔다 (추측 금지, TRD §3.1). */
export function toFormValues(d: ResumeData | null | undefined): ResumeFormValues {
  if (!d) return emptyResumeForm();
  const edu = (d.education ?? []).map((e) => ({ school: str(e.school), major: str(e.major), degree: str(e.degree), start: str(e.start), end: str(e.end) }));
  return {
    name: str(d.name),
    education: edu.length ? edu : [{ school: "", major: "", degree: "", start: "", end: "" }],
    experience: (d.experience ?? []).map((e) => ({ company: str(e.company), role: str(e.role), start: str(e.start), end: str(e.end), summary: str(e.summary) })),
    projects: (d.projects ?? []).map((p) => ({ title: str(p.title), role: str(p.role), period: str(p.period), tech_stack: (p.tech_stack ?? []).join(", "), description: str(p.description) })),
    skills: [...(d.skills ?? [])],
    certifications: [...(d.certifications ?? [])],
    self_intro: str(d.self_intro),
  };
}

const blankEdu = (e: EducationRow) => !(e.school || e.major || e.degree || e.start || e.end).trim();
const blankExp = (e: ExperienceRow) => !(e.company || e.role || e.start || e.end || e.summary).trim();
const blankPrj = (p: ProjectRow) => !(p.title || p.role || p.period || p.tech_stack || p.description).trim();

/** 폼 → 서버. 완전히 빈 행은 버리고, 빈 문자열은 null 로 보낸다. */
export function toResumeData(v: ResumeFormValues): ResumeData {
  return {
    name: orNull(v.name),
    education: v.education.filter((e) => !blankEdu(e)).map((e) => ({ school: orNull(e.school), major: orNull(e.major), degree: orNull(e.degree), start: orNull(e.start), end: orNull(e.end) })),
    experience: v.experience.filter((e) => !blankExp(e)).map((e) => ({ company: orNull(e.company), role: orNull(e.role), start: orNull(e.start), end: orNull(e.end), summary: orNull(e.summary) })),
    projects: v.projects.filter((p) => !blankPrj(p)).map((p) => ({
      title: orNull(p.title), role: orNull(p.role), period: orNull(p.period), description: orNull(p.description),
      tech_stack: p.tech_stack.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
    })),
    skills: v.skills.map((s) => s.trim()).filter(Boolean),
    certifications: v.certifications.map((s) => s.trim()).filter(Boolean),
    self_intro: orNull(v.self_intro),
  };
}

export interface BasicInfoIssues { name: boolean; career: boolean }

/** 성명 + (학교명이 있는 학력 또는 회사명이 있는 경력 1건 이상). 자소서는 필수가 아니다 (PRD 10장 #9·#10). */
export function basicInfoIssues(v: ResumeFormValues): BasicInfoIssues {
  return {
    name: v.name.trim() === "",
    career: !(v.education.some((e) => e.school.trim() !== "") || v.experience.some((e) => e.company.trim() !== "")),
  };
}
export const isBasicInfoComplete = (v: ResumeFormValues): boolean => {
  const i = basicInfoIssues(v);
  return !i.name && !i.career;
};

/** 클라이언트 1차 검증: 위반하면 업로드 요청 자체를 보내지 않는다 (UI_SPEC §4.3.3). 통과면 null. */
export function validatePdfFile(f: { name: string; type: string; size: number }): string | null {
  const okExt = /\.pdf$/i.test(f.name);
  const okMime = f.type === "" || f.type === "application/pdf";  // 일부 환경은 MIME 을 비워서 준다 — 확장자와 서버 검증이 보완한다
  if (!okExt || !okMime) return PDF_ONLY_MESSAGE;
  if (f.size > MAX_PDF_BYTES) return PDF_SIZE_MESSAGE;
  if (f.size === 0) return "빈 파일입니다. 다른 PDF를 선택해 주세요.";
  return null;
}
