"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { createSchedule, deleteSchedule, scheduleKeys, updateSchedule } from "../api";
import { TYPE_LABEL, isPast, overlapping, toLocalInput, type Sched } from "../calendar/calendar-logic";

const schema = z.object({
  title: z.string().trim().min(1, "제목을 입력해 주세요").max(100),
  type: z.enum(["interview1", "interview2", "doc_screen", "deadline"]),
  starts_at: z.string().min(1, "시작 일시를 선택해 주세요"),
  ends_at: z.string().optional(),
}).refine((v) => !v.ends_at || v.ends_at > v.starts_at, { path: ["ends_at"], message: "종료는 시작 이후여야 해요" });
type Form = z.infer<typeof schema>;

/**
 * 일정 추가/수정/삭제 모달 (대시보드·캘린더 공용, UI_SPEC §5.7). `schedule` 이 있으면 수정 모드.
 * 시간이 겹쳐도 저장은 막지 않고 경고만 한다. 지난 일정을 수정·삭제할 때는 확인을 받는다.
 */
export function ScheduleFormDialog({ open, onClose, schedule, defaultStart, existing = [] }: {
  open: boolean; onClose: () => void; schedule?: Sched | null; defaultStart?: string; existing?: Sched[];
}) {
  return (
    <Modal open={open} title={schedule ? "일정 수정" : "면접 일정 추가"} onClose={onClose}>
      {/* 열릴 때마다 새로 마운트해 초기값을 defaultValues 로 준다(effect 로 reset 하면 입력 직후 값이 지워지는 경쟁이 생긴다) */}
      <ScheduleForm key={schedule?.id ?? `new-${defaultStart ?? ""}`} onClose={onClose} schedule={schedule} defaultStart={defaultStart} existing={existing} />
    </Modal>
  );
}

function ScheduleForm({ onClose, schedule, defaultStart, existing }: { onClose: () => void; schedule?: Sched | null; defaultStart?: string; existing: Sched[] }) {
  const qc = useQueryClient();
  const { register, handleSubmit, watch, formState: { errors } } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: schedule ? { title: schedule.title, type: schedule.type as Form["type"], starts_at: toLocalInput(schedule.starts_at), ends_at: toLocalInput(schedule.ends_at) }
      : { title: "", type: "interview1", starts_at: defaultStart ?? "", ends_at: "" },
  });

  const done = (msg: string) => { toast.success(msg); void qc.invalidateQueries({ queryKey: ["admin", "dashboard"] }); void qc.invalidateQueries({ queryKey: scheduleKeys.all }); onClose(); };
  const fail = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "처리하지 못했어요");
  const body = (v: Form) => ({ title: v.title, type: v.type, starts_at: new Date(v.starts_at).toISOString(), ends_at: v.ends_at ? new Date(v.ends_at).toISOString() : null });
  const save = useMutation({
    mutationFn: (v: Form) => (schedule ? updateSchedule(schedule.id, { ...body(v), job_id: schedule.job_id, application_id: schedule.application_id }) : createSchedule(body(v))),
    onSuccess: () => done(schedule ? "일정을 수정했어요" : "면접 일정을 추가했어요"), onError: fail,
  });
  const del = useMutation({ mutationFn: () => deleteSchedule(schedule!.id), onSuccess: () => done("일정을 삭제했어요"), onError: fail });

  const w = watch();
  const clash = w.starts_at ? overlapping(existing, { starts_at: new Date(w.starts_at).toISOString(), ends_at: w.ends_at ? new Date(w.ends_at).toISOString() : null }, schedule?.id) : [];
  const field = "h-10 w-full rounded border border-border bg-surface px-3 text-sm";
  const submit = handleSubmit((v) => {
    if (schedule && isPast(schedule.starts_at) && !window.confirm("이미 지난 일정입니다. 수정할까요?")) return;
    save.mutate(v);
  });
  return (
    <>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <label className="block text-sm">제목<input {...register("title")} className={field} aria-invalid={!!errors.title} />{errors.title && <span role="alert" className="text-xs text-danger">{errors.title.message}</span>}</label>
        <label className="block text-sm">유형<select {...register("type")} className={field}>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="block text-sm">시작<input type="datetime-local" {...register("starts_at")} className={field} />{errors.starts_at && <span role="alert" className="text-xs text-danger">{errors.starts_at.message}</span>}</label>
        <label className="block text-sm">종료(선택)<input type="datetime-local" {...register("ends_at")} className={field} />{errors.ends_at && <span role="alert" className="text-xs text-danger">{errors.ends_at.message}</span>}</label>
        {clash.length > 0 && <p role="status" className="rounded bg-warning-bg p-2 text-xs text-warning" data-testid="overlap-warning">⚠ 같은 시간대에 일정이 있어요: {clash.map((c) => c.title).join(", ")} (저장은 가능합니다)</p>}
        <div className="flex justify-between gap-2">
          {schedule ? <Button type="button" variant="danger" loading={del.isPending} data-testid="schedule-delete"
            onClick={() => { if (window.confirm(isPast(schedule.starts_at) ? "이미 지난 일정입니다. 삭제할까요?" : "이 일정을 삭제할까요?")) del.mutate(); }}>삭제</Button> : <span />}
          <div className="flex gap-2"><Button type="button" variant="secondary" onClick={onClose}>취소</Button><Button type="submit" loading={save.isPending}>{schedule ? "저장" : "추가"}</Button></div>
        </div>
      </form>
    </>
  );
}
