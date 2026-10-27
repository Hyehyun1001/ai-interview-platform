/** 서버(미들웨어)와 클라이언트가 공유하는 순수 리다이렉트 규칙. React/TanStack 에 의존하지 않는다. */
export type Role = "applicant" | "recruiter" | "admin";

export const homeFor = (role: Role | string): string => (role === "applicant" ? "/jobs" : "/admin");

/**
 * 로그인 후 이동 경로 검증. 외부 사이트로의 리다이렉트(open redirect)를 막기 위해
 * 같은 출처의 절대 경로("/..." 이면서 "//" 나 "/\\" 로 시작하지 않는 것)만 허용한다.
 */
export function safeNext(next: string | null | undefined, fallback: string): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\") || /[\r\n]/.test(next)) return fallback;
  return next;
}
