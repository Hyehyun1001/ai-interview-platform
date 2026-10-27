"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { createSchedule } from "../api";

const schema = z.object({
  title: z.string().trim().min(1, "제목을 입력해 주세요").max(100),
  type: z.enum(["interview1", "interview2", "doc_screen", "deadline"]),
  starts_at: z.string().min(1, "시작 일시를 선택해 주세요"),
  ends_at: z.string().optional(),
}).refine((v) => !v.ends_at || v.ends_at > v.starts_at, { path: ["ends_at"], message: "종료는 시작 이후여야 해요" });
type Form = z.infer<typeof schema>;

const TYPES: Record<Form["type"], string> = { interview1: "1차 면접", interview2: "2차 면접", doc_screen: "서류 검토", deadline: "마감" };

export function ScheduleFormDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { type: "interview1" } });
  const m = useMutation({
    mutationFn: (v: Form) => createSchedule({ title: v.title, type: v.type, starts_at: new Date(v.starts_at).toISOString(), ends_at: v.ends_at ? new Date(v.ends_at).toISOString() : null }),
    onSuccess: () => { toast.success("면접 일정을 추가했어요"); void qc.invalidateQueries({ queryKey: ["admin", "dashboard"] }); reset(); onClose(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "일정을 추가하지 못했어요"),
  });
  const field = "h-10 w-full rounded border border-border bg-surface px-3 text-sm";
  return (
    <Modal open={open} title="면접 일정 추가" onClose={onClose}>
      <form onSubmit={handleSubmit((v) => m.mutate(v))} className="space-y-3" noValidate>
        <label className="block text-sm">제목<input {...register("title")} className={field} aria-invalid={!!errors.title} />{errors.title && <span role="alert" className="text-xs text-danger">{errors.title.message}</span>}</label>
        <label className="block text-sm">유형<select {...register("type")} className={field}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="block text-sm">시작<input type="datetime-local" {...register("starts_at")} className={field} />{errors.starts_at && <span role="alert" className="text-xs text-danger">{errors.starts_at.message}</span>}</label>
        <label className="block text-sm">종료(선택)<input type="datetime-local" {...register("ends_at")} className={field} />{errors.ends_at && <span role="alert" className="text-xs text-danger">{errors.ends_at.message}</span>}</label>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>취소</Button><Button type="submit" loading={m.isPending}>추가</Button></div>
      </form>
    </Modal>
  );
}
