/**
 * fetch 래퍼. 인증은 HttpOnly 쿠키(자동 전송)이며 토큰을 JS 로 다루지 않는다 (UI_SPEC §3.2, §8).
 * 에러 형식은 TRD §7 공통 `{"error":{"code","message","details","request_id"}}`.
 * (OpenAPI 는 422 를 FastAPI 기본 HTTPValidationError 로 선언하지만 실제 응답은 이 형식이다.)
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Record<string, unknown> = {},
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 필드 인라인 오류 (422 VALIDATION_ERROR) */
  get fieldErrors(): { field: string; message: string }[] {
    const f = this.details["fields"];
    return Array.isArray(f) ? (f as { field: string; message: string }[]) : [];
  }
}

type ErrorBody = { error?: { code?: string; message?: string; details?: Record<string, unknown>; request_id?: string } };

export async function parseError(res: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await res.json()) as ErrorBody;
  } catch {
    /* JSON 이 아닌 응답(프록시 오류 등) */
  }
  const e = body.error;
  return new ApiError(res.status, e?.code ?? `HTTP_${res.status}`, e?.message ?? res.statusText ?? "요청에 실패했습니다", e?.details ?? {}, e?.request_id ?? res.headers.get("x-request-id") ?? undefined);
}

let refreshing: Promise<boolean> | null = null;

/** access 토큰 만료 시 refresh 쿠키로 1회 재발급. 동시 요청은 하나의 갱신을 공유한다. */
async function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export interface FetchOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  /** 401 시 자동 갱신을 시도하지 않는다 (로그인·갱신 자체 호출) */
  noRefresh?: boolean;
}

export async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const { json, noRefresh, headers, ...rest } = opts;
  const init: RequestInit = {
    credentials: "include",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : undefined,
  };
  let res = await fetch(path, init);
  if (res.status === 401 && !noRefresh && (await refreshSession())) res = await fetch(path, init);
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
