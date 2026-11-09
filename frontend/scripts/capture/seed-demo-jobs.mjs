import { request } from "@playwright/test";
import { fillDemoJobs } from "./demo-jobs.mjs";

const ctx = await request.newContext({ baseURL: process.argv[2] ?? "http://localhost:8000" });
console.log(`공고 ${await fillDemoJobs(ctx)}개 추가`);
await ctx.dispose();
