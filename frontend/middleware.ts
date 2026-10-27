import { NextResponse, type NextRequest } from "next/server";
import { homeFor, safeNext } from "@/lib/redirect";

/**
 * 영역 분리용 *편의* 리다이렉트. access 토큰의 role 클레임을 서명 검증 없이 읽을 뿐이므로 보안 경계가 아니다 —
 * 실제 인가는 항상 API(RBAC)가 한다. 토큰이 없거나 만료되었을 때의 처리는 클라이언트 AuthGuard 가 맡는다
 * (refresh 쿠키는 /api/v1/auth 경로에만 전송되어 미들웨어에서는 볼 수 없다).
 *
 * `/login` 은 **쿠키가 아니라 백엔드 `/me` 응답**으로 판단한다: 만료·폐기된 쿠키가 남아 있을 때 쿠키만 보고 리다이렉트하면
 * 로그인 ↔ 홈 무한 루프가 생기기 때문이다. `/me` 가 200 일 때만 역할별 홈(또는 안전한 next)으로 보내고, 그 외(401·백엔드 불가·타임아웃)는
 * 로그인 화면을 그대로 보여 준다.
 */
const APPLICANT_PREFIXES = ["/jobs", "/mypage", "/apply", "/interview", "/reports"];
const ME_TIMEOUT_MS = 1500;

function roleOf(token: string | undefined): string | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const role = (JSON.parse(json) as { role?: unknown }).role;
    return typeof role === "string" ? role : null;
  } catch {
    return null;
  }
}

/** 로그인 상태 확인. 로그인되어 있으면 role, 아니면(어떤 이유로든) null. */
async function sessionRole(req: NextRequest): Promise<string | null> {
  const cookie = req.headers.get("cookie");
  if (!cookie || !req.cookies.get("access_token")) return null;  // 쿠키가 없으면 백엔드 호출 자체를 생략
  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${backend}/api/v1/me`, { headers: { cookie }, signal: AbortSignal.timeout(ME_TIMEOUT_MS), cache: "no-store" });
    if (!res.ok) return null;
    const role = ((await res.json()) as { role?: unknown }).role;
    return typeof role === "string" ? role : null;
  } catch {
    return null;
  }
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname === "/login") {
    const role = await sessionRole(req);
    if (!role) return NextResponse.next();
    const target = safeNext(req.nextUrl.searchParams.get("next"), homeFor(role));
    return NextResponse.redirect(new URL(target, req.url));
  }
  const role = roleOf(req.cookies.get("access_token")?.value);
  if (pathname.startsWith("/admin") && role === "applicant") return NextResponse.redirect(new URL("/jobs", req.url));
  if (APPLICANT_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`)) && (role === "recruiter" || role === "admin"))
    return NextResponse.redirect(new URL("/admin", req.url));
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/|api/|favicon.ico|mediapipe/|audio/).*)"] };
