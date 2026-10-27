"use client";
import { ChevronDown, Lock } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";

/**
 * 개인정보 활용 동의 모달 (UI_SPEC §4.2.2, NFR-S5). 두 항목 모두 필수이며, 둘 다 체크해야 [동의하고 계속]이 활성화된다.
 * 요청 실패 시 모달을 유지하고 오류를 보여 준다(부모가 error 를 넘긴다).
 */
export function ConsentDialog({ open, busy, error, onCancel, onAgree }: {
  open: boolean; busy: boolean; error: string | null; onCancel: () => void; onAgree: () => void;
}) {
  const [privacy, setPrivacy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [terms, setTerms] = useState(false);
  const termsId = useId();
  useEffect(() => { if (open) { setPrivacy(false); setRecording(false); setTerms(false); } }, [open]);

  return (
    <Modal open={open} title="개인정보 활용 동의" onClose={() => { if (!busy) onCancel(); }}>
      <div className="space-y-4">
        <div className="rounded bg-info-bg p-3 text-sm text-info">
          <p className="flex items-center gap-1 font-semibold"><Lock className="h-4 w-4" aria-hidden />데이터 보안 고지</p>
          <p className="mt-1">모든 음성·영상·이력서 데이터는 기업 내부망 서버 내에서만 저장·처리됩니다.</p>
          <p className="mt-1 text-xs">수집 항목: 이력서·자소서, 면접 음성/영상/답변 텍스트, 시선 이탈 이벤트</p>
        </div>
        <div>
          <button type="button" aria-expanded={terms} aria-controls={termsId} onClick={() => setTerms((v) => !v)} className="flex items-center gap-1 text-sm text-primary">
            약관 요약 보기 <ChevronDown className={`h-4 w-4 transition ${terms ? "rotate-180" : ""}`} aria-hidden />
          </button>
          {terms && (
            <ul id={termsId} className="mt-2 list-disc space-y-1 rounded border border-border p-3 pl-6 text-xs text-muted">
              <li>수집·이용 목적: 모의면접 진행, AI 평가 리포트 생성, 채용 담당자의 지원자 검토</li>
              <li>보관 위치: 기업 내부망 서버 (외부 전송 없음)</li>
              <li>면접 영상은 시선 분석에 브라우저 안에서만 쓰이고, 녹화는 사내 서버에 저장됩니다.</li>
              <li>삭제 요청은 마이페이지에서 할 수 있습니다.</li>
            </ul>
          )}
        </div>
        <div className="space-y-2">
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1 h-4 w-4" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} /><span>(필수) 개인정보 수집·이용에 동의합니다</span></label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1 h-4 w-4" checked={recording} onChange={(e) => setRecording(e.target.checked)} /><span>(필수) 면접 음성·영상 녹화·저장 및 AI 평가에 동의합니다</span></label>
        </div>
        {error && <p role="alert" className="rounded bg-danger-bg p-2 text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>취소</Button>
          <Button onClick={onAgree} disabled={!(privacy && recording)} loading={busy}>{error ? "다시 시도" : "동의하고 계속"}</Button>
        </div>
      </div>
    </Modal>
  );
}
