"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { fetchResumeJob, uploadResumePdf } from "@/features/applicant/api";
import type { ResumeData } from "./schema";

export type Extraction =
  | { phase: "idle" }
  | { phase: "uploading"; fileName: string; pct: number }
  | { phase: "extracting"; fileName: string }
  | { phase: "slow"; fileName: string }
  | { phase: "done"; fileName: string; data: ResumeData; fellBack: boolean }
  | { phase: "failed"; message: string };

const POLL_MS = 1500;
const SLOW_AFTER_MS = 60_000;  // 60초가 지나면 "오래 걸리고 있어요" 안내 (UI_SPEC §4.3.6)

const UPLOAD_ERRORS: Record<number, string> = {
  413: "10MB 이하의 PDF만 업로드할 수 있습니다.",
  415: "PDF 파일만 업로드할 수 있습니다.",
  422: "20쪽 이하의 PDF만 가능합니다.",
};

/** PDF 업로드 → 추출 작업 polling(1.5초). 취소하면 진행 중인 요청·polling 을 모두 멈춘다. */
export function useResumeExtraction() {
  const [state, setState] = useState<Extraction>({ phase: "idle" });
  const abort = useRef<AbortController | null>(null);
  const run = useRef(0);  // 취소/재시작 시 이전 polling 루프를 무효화하는 세대 번호

  const stop = useCallback(() => { run.current++; abort.current?.abort(); abort.current = null; }, []);
  useEffect(() => stop, [stop]);

  const poll = useCallback(async (jobId: string, fileName: string, gen: number) => {
    const started = Date.now();
    while (gen === run.current) {
      if (Date.now() - started > SLOW_AFTER_MS) { setState({ phase: "slow", fileName }); return jobId; }
      try {
        const job = await fetchResumeJob(jobId);
        if (gen !== run.current) return null;
        if (job.status === "done" && job.data) { setState({ phase: "done", fileName, data: job.data, fellBack: job.fell_back }); return null; }
        if (job.status === "failed") {
          setState({ phase: "failed", message: job.error_message ?? "파일을 읽을 수 없습니다. 다른 파일을 올리거나 직접 작성해 주세요." });
          return null;
        }
      } catch (e) {
        if (gen !== run.current) return null;
        setState({ phase: "failed", message: e instanceof ApiError && e.status === 404 ? "추출 작업이 만료되었어요. 다시 올려 주세요." : "추출 상태를 확인하지 못했어요. 다시 시도해 주세요." });
        return null;
      }
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
    return null;
  }, []);

  const jobRef = useRef<{ id: string; name: string } | null>(null);

  const start = useCallback(async (file: File) => {
    stop();
    const gen = ++run.current;
    const ctl = new AbortController();
    abort.current = ctl;
    setState({ phase: "uploading", fileName: file.name, pct: 0 });
    try {
      const { job_id } = await uploadResumePdf(file, (pct) => { if (gen === run.current) setState({ phase: "uploading", fileName: file.name, pct }); }, ctl.signal);
      if (gen !== run.current) return;
      jobRef.current = { id: job_id, name: file.name };
      setState({ phase: "extracting", fileName: file.name });
      await poll(job_id, file.name, gen);
    } catch (e) {
      if (gen !== run.current || (e instanceof DOMException && e.name === "AbortError")) return;
      setState({ phase: "failed", message: e instanceof ApiError ? (UPLOAD_ERRORS[e.status] ?? e.message) : "업로드에 실패했어요. 네트워크를 확인하고 다시 시도해 주세요." });
    }
  }, [poll, stop]);

  /** "계속 기다리기": 같은 작업을 다시 60초 동안 polling 한다. */
  const keepWaiting = useCallback(() => {
    const j = jobRef.current;
    if (!j) return;
    const gen = ++run.current;
    setState({ phase: "extracting", fileName: j.name });
    void poll(j.id, j.name, gen);
  }, [poll]);

  const cancel = useCallback(() => { stop(); setState({ phase: "idle" }); }, [stop]);
  return { state, start, cancel, keepWaiting };
}
