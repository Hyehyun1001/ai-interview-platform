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
export const fetchMe = () => apiFetch<UserOut>("/api/v1/me");

export const ME_KEY = ["me"] as const;
export const useMe = () => useQuery({ queryKey: ME_KEY, queryFn: fetchMe, retry: false, staleTime: 60_000 });

export { homeFor, safeNext } from "@/lib/redirect";
