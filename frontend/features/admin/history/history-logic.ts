export const NOTI_LABEL: Record<string, string> = {
  new_application: "새 지원이 들어왔어요", report_ready: "리포트가 완료됐어요", schedule_confirmed: "일정이 확정됐어요", deadline_d1: "공고 마감이 하루 남았어요",
};
export const ACTION_LABEL: Record<string, string> = {
  created: "작성", published: "게시", closed: "마감", expired: "만료", deleted: "삭제", template_saved: "템플릿으로 저장", template_applied: "템플릿 적용",
};

/** 알림 클릭 시 이동할 화면. payload 에는 식별자만 있다. 알 수 없는 유형이면 이동하지 않는다(null). */
export function notificationHref(type: string, payload: Record<string, unknown> | null | undefined): string | null {
  const p = payload ?? {};
  const app = typeof p["application_id"] === "string" ? p["application_id"] : null;
  const job = typeof p["job_id"] === "string" ? p["job_id"] : null;
  switch (type) {
    case "report_ready": return app ? `/admin/applications/${app}` : null;
    case "new_application": return job ? `/admin/jobs/${job}/applicants` : "/admin/applicants";
    case "schedule_confirmed": return "/admin/calendar";
    case "deadline_d1": return job ? `/admin/jobs/${job}/edit?step=4` : "/admin/jobs";
    default: return null;
  }
}
