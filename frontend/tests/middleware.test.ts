// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { middleware } from "@/middleware";

const jwt = (role: string) => `h.${Buffer.from(JSON.stringify({ role })).toString("base64url")}.s`;
const req = (path: string, token?: string) =>
  new NextRequest(`http://localhost:3000${path}`, { headers: token ? { cookie: `access_token=${token}` } : {} });
const mockMe = (status: number, body: unknown = {}) => vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

afterEach(() => vi.unstubAllGlobals());

describe("/login redirect for signed-in users", () => {
  it("applicant → /jobs, recruiter → /admin", async () => {
    mockMe(200, { role: "applicant" });
    expect((await middleware(req("/login", jwt("applicant")))).headers.get("location")).toBe("http://localhost:3000/jobs");
    mockMe(200, { role: "recruiter" });
    expect((await middleware(req("/login", jwt("recruiter")))).headers.get("location")).toBe("http://localhost:3000/admin");
    mockMe(200, { role: "admin" });
    expect((await middleware(req("/login", jwt("admin")))).headers.get("location")).toBe("http://localhost:3000/admin");
  });
  it("honours a safe ?next but ignores an open-redirect attempt", async () => {
    mockMe(200, { role: "applicant" });
    expect((await middleware(req("/login?next=/interview/abc", jwt("applicant")))).headers.get("location")).toBe("http://localhost:3000/interview/abc");
    expect((await middleware(req("/login?next=//evil.com", jwt("applicant")))).headers.get("location")).toBe("http://localhost:3000/jobs");
    expect((await middleware(req("/login?next=https://evil.com", jwt("applicant")))).headers.get("location")).toBe("http://localhost:3000/jobs");
  });
  it("does NOT redirect when the cookie is stale (backend says 401) — no login/home loop", async () => {
    mockMe(401, { error: {} });
    expect((await middleware(req("/login", jwt("applicant")))).headers.get("location")).toBeNull();
  });
  it("does NOT redirect when the backend is unreachable or has no cookie", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    expect((await middleware(req("/login", jwt("applicant")))).headers.get("location")).toBeNull();
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    expect((await middleware(req("/login"))).headers.get("location")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });
  it("forwards the cookie to /me and never trusts the token alone", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ role: "applicant" }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    await middleware(req("/login", "forged"));
    expect(f).toHaveBeenCalledTimes(1);
    const init = (f.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(String((init.headers as Record<string, string>).cookie)).toContain("access_token=forged");
  });
});

describe("area separation", () => {
  it("keeps applicants out of /admin and staff out of applicant pages", async () => {
    expect((await middleware(req("/admin", jwt("applicant")))).headers.get("location")).toBe("http://localhost:3000/jobs");
    expect((await middleware(req("/jobs", jwt("recruiter")))).headers.get("location")).toBe("http://localhost:3000/admin");
    expect((await middleware(req("/jobs", jwt("applicant")))).headers.get("location")).toBeNull();
  });
});
