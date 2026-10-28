"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { Badge, Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { adminKeys, decide, markReviewed, regenerateReport, sendMail } from "../api";
import type { ApplicationDetail } from "@/types/admin";

const LABEL = { pending: "결정 대기", pass: "합격", fail: "불합격" } as const;
type Decision = keyof typeof LABEL;

/** 열람 확인: 상세 화면에 2초 이상 머문 뒤 1회 호출한다 (GET 부작용 금지, UI_SPEC §5.6.4). 리포트 완료 건만 의미가 있다. */
export function useMarkReviewed(applicationId: string, enabled: boolean) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    const t = setTimeout(() => { void markReviewed(applicationId).then(() => qc.invalidateQueries({ queryKey: ["admin", "dashboard"] })).catch(() => undefined); }, 2000);
    return () => clearTimeout(t);
  }, [applicationId, enabled, qc]);
}

export function DecisionPanel({ app }: { app: ApplicationDetail }) {
  const qc = useQueryClient();
  const [dlg, setDlg] = useState<{ decision: Decision; ack: boolean } | null>(null);
  const [memo, setMemo] = useState("");
  const [mailOpen, setMailOpen] = useState(false);
  const [template, setTemplate] = useState<"pass" | "fail" | "schedule">("pass");
  const [link, setLink] = useState("");
  const ready = app.report_status === "done";
  const invalidate = () => { void qc.invalidateQueries({ queryKey: adminKeys.application(app.application_id) }); void qc.invalidateQueries({ queryKey: ["admin", "dashboard"] }); };

  const decideM = useMutation({
    mutationFn: (v: { decision: Decision; ack: boolean }) => decide(app.application_id, { decision: v.decision, memo: memo || null, acknowledge_notified: v.ack }),
    onSuccess: (_r, v) => { toast.success(v.decision === "pending" ? "결정을 취소했어요" : `${LABEL[v.decision]} 처리했어요`); setDlg(null); setMemo(""); invalidate(); },
    onError: (e, v) => {
      if (e instanceof ApiError && e.code === "DECISION_ALREADY_NOTIFIED") { setDlg({ decision: v.decision, ack: true }); toast.warning("이미 결과 메일을 보냈습니다. 변경하시겠어요?"); }
      else toast.error(e instanceof ApiError ? e.message : "결정을 저장하지 못했어요");
    },
  });
  const mailM = useMutation({
    mutationFn: () => sendMail(app.application_id, { template, schedule_link: template === "schedule" ? link : null }),
    onSuccess: () => { toast.success("안내 메일을 보냈어요"); setMailOpen(false); invalidate(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "메일 발송에 실패했어요"),
  });
  const regen = useMutation({ mutationFn: () => regenerateReport(app.application_id), onSuccess: () => { toast.success("리포트 재생성을 요청했어요"); invalidate(); }, onError: (e) => toast.error(e instanceof ApiError ? e.message : "요청에 실패했어요") });

  return (
    <div className="space-y-3" data-testid="decision-panel">
      {app.report_status === "failed" && <p role="alert" className="flex items-center gap-3 rounded bg-danger-bg p-3 text-sm text-danger">리포트 생성에 실패했어요
        <Button variant="secondary" loading={regen.isPending} onClick={() => regen.mutate()}>재생성 요청</Button></p>}
      {(app.report_status === "queued" || app.report_status === "running") && <p role="status" className="rounded bg-info-bg p-3 text-sm text-info">리포트를 생성하고 있어요. 완료되면 결정할 수 있습니다.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={app.final_decision === "pass" ? "success" : app.final_decision === "fail" ? "danger" : "neutral"} data-testid="decision-badge">{LABEL[app.final_decision]}</Badge>
        {/* 두 버튼은 같은 모양이고, 실제로 선택된 결정(합격/불합격)만 파란색으로 강조한다 — 파란 버튼이 "추천"처럼 보이지 않게 */}
        <Button variant={app.final_decision === "pass" ? "primary" : "secondary"} aria-pressed={app.final_decision === "pass"} disabled={!ready} onClick={() => setDlg({ decision: "pass", ack: false })} data-testid="decision-pass">합격 처리</Button>
        <Button variant={app.final_decision === "fail" ? "primary" : "secondary"} aria-pressed={app.final_decision === "fail"} disabled={!ready} onClick={() => setDlg({ decision: "fail", ack: false })} data-testid="decision-fail">불합격 처리</Button>
        {app.final_decision !== "pending" && <Button variant="ghost" disabled={!ready} onClick={() => setDlg({ decision: "pending", ack: false })}>결정 취소</Button>}
        <Button variant="secondary" onClick={() => { setTemplate(app.final_decision === "fail" ? "fail" : app.final_decision === "pass" ? "pass" : "schedule"); setMailOpen(true); }}>안내 메일</Button>
      </div>
      <Modal open={!!dlg} title={dlg ? (dlg.decision === "pending" ? "결정 취소" : `${LABEL[dlg.decision]} 처리`) : ""} onClose={() => setDlg(null)}>
        <div className="space-y-3 text-sm">
          <p>{dlg?.ack ? "이미 결과 메일을 보낸 지원자입니다. 결정을 바꾸면 안내 내용과 달라질 수 있어요." : "결정은 나중에 바꿀 수 있고 변경 이력은 기록됩니다. AI 예상과 달라도 그대로 저장됩니다."}</p>
          <label className="block">메모 (내부용, 지원자에게 보이지 않음)<textarea className="mt-1 h-24 w-full rounded border border-border bg-surface p-2" value={memo} maxLength={1000} onChange={(e) => setMemo(e.target.value)} /></label>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setDlg(null)}>취소</Button>
            <Button loading={decideM.isPending} onClick={() => dlg && decideM.mutate(dlg)} data-testid="decision-confirm">{dlg?.ack ? "변경 확인" : "확인"}</Button></div>
        </div>
      </Modal>
      <Modal open={mailOpen} title="안내 메일 발송" onClose={() => setMailOpen(false)}>
        <div className="space-y-3 text-sm">
          <label className="block">템플릿<select className="mt-1 h-10 w-full rounded border border-border bg-surface px-2" value={template} onChange={(e) => setTemplate(e.target.value as typeof template)}>
            <option value="pass">합격 안내</option><option value="fail">불합격 안내</option><option value="schedule">일정 조율</option></select></label>
          {template === "schedule" && <label className="block">일정 조율 링크<input className="mt-1 h-10 w-full rounded border border-border bg-surface px-2" placeholder="https://" value={link} onChange={(e) => setLink(e.target.value)} /></label>}
          {template !== "schedule" && app.final_decision !== template && <p role="alert" className="text-warning">현재 최종 결정({LABEL[app.final_decision]})과 맞지 않아 발송되지 않습니다. 먼저 결정을 처리해 주세요.</p>}
          <p className="text-xs text-muted">발송한 메일은 되돌릴 수 없습니다. 메일에는 AI 점수·예상 합불이 포함되지 않습니다.</p>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setMailOpen(false)}>취소</Button>
            <Button loading={mailM.isPending} disabled={template === "schedule" && !/^https?:\/\/\S+$/.test(link)} onClick={() => { if (window.confirm("메일을 발송할까요? 되돌릴 수 없습니다.")) mailM.mutate(); }} data-testid="mail-send">발송</Button></div>
        </div>
      </Modal>
    </div>
  );
}
