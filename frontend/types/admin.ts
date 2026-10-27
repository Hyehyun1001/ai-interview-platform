/**
 * 관리자 API 타입 — **OpenAPI 생성 타입(types/api.ts)의 별칭**이다. 직접 정의하지 않는다 (CLAUDE.md: 타입은 OpenAPI 에서 생성).
 * 백엔드 스키마가 바뀌면 `npm run gen:types` 로 api.ts 를 다시 만든다.
 */
import type { components } from "./api";

type S = components["schemas"];

export type DashboardResponse = S["DashboardResponse"];
export type DashboardRange = DashboardResponse["range"];
export type DashboardSummary = S["DashboardSummary"];
export type JobCategoryStat = S["JobCategoryStat"];
export type RecentJob = S["RecentJob"];
export type RecentApplicant = S["RecentApplicant"];
export type AiPassPrediction = RecentApplicant["ai_pass_prediction"];
export type ReportStatus = RecentApplicant["report_status"];
export type FinalDecision = RecentApplicant["final_decision"];
export type JobStatus = RecentJob["status"];

export type SystemMetrics = S["SystemMetrics"];
export type NotificationItem = S["NotificationItem"];
export type NotificationsResponse = S["NotificationsResponse"];

export type ScheduleCreate = S["ScheduleCreate"];
export type ScheduleType = ScheduleCreate["type"];

export type ApplicationDetail = S["ApplicationDetail"];
export type TimelineResponse = S["TimelineResponse"];
export type TimelineTurn = S["TimelineTurn"];
export type TimelineSegment = S["TimelineSegment"];
export type SegmentKind = TimelineSegment["kind"];
export type TimelineWord = S["TimelineWord"];
export type GazeEventDto = S["GazeEventOut"];
export type TurnReviewScore = S["TurnReviewScore"];
