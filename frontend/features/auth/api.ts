import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import type { components } from "@/types/api";

export type UserOut = components["schemas"]["UserOut"];
export type UserRole = components["schemas"]["UserRole"];
export type LoginRole = components["schemas"]["LoginRole"];
export type AuthResponse = components["schemas"]["AuthResponse"];
export type LoginRequest = components["schemas"]["LoginRequest"];

export const login = (body: LoginRequest) => apiFetch<AuthResponse>("/api/v1/auth/login", { method: "POST", json: body, noRefresh: true });
export const logout = () => apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
export type RegisterRequest = components["schemas"]["RegisterRequest"];
export const register = (body: RegisterRequest) => apiFetch<AuthResponse>("/api/v1/auth/register", { method: "POST", json: body, noRefresh: true });
export type ProfileOut = components["schemas"]["ProfileOut"];
export type ProfilePatch = components["schemas"]["ProfilePatch"];
export const fetchMe = () => apiFetch<UserOut>("/api/v1/me");
export const fetchProfile = () => apiFetch<ProfileOut>("/api/v1/me");
export const patchProfile = (body: ProfilePatch) => apiFetch<ProfileOut>("/api/v1/me", { method: "PATCH", json: body });
export const deleteAccount = (password: string) => apiFetch<void>("/api/v1/me", { method: "DELETE", json: { password } });

export const ME_KEY = ["me"] as const;
export const useMe = () => useQuery({ queryKey: ME_KEY, queryFn: fetchMe, retry: false, staleTime: 60_000 });

export { homeFor, safeNext } from "@/lib/redirect";
