import type { APIRequestContext } from "@playwright/test";
export function fillDemoJobs(request: APIRequestContext, creds?: { email?: string; password?: string }): Promise<number>;
