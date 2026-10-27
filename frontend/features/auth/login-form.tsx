"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ME_KEY, homeFor, login, safeNext, type LoginRole } from "./api";

// 이메일 검증은 백엔드와 동일하게 형식만 본다 (사내 도메인 .local 허용, UI_SPEC §4.1.1)
const schema = z.object({
  email: z.string().trim().min(1, "이메일을 입력하세요").regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, "이메일 형식이 올바르지 않습니다"),
  password: z.string().min(1, "비밀번호를 입력하세요"),  // 로그인은 빈 값만 검증 (규칙 노출 방지)
});
type Values = z.infer<typeof schema>;

const ROLES: { value: LoginRole; label: string }[] = [{ value: "applicant", label: "지원자" }, { value: "recruiter", label: "담당자" }];

export function LoginForm() {
  const [role, setRole] = useState<LoginRole>("applicant");
  const [formError, setFormError] = useState<string | null>(null);
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { register, handleSubmit, setFocus, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      const res = await login({ ...v, role });
      qc.setQueryData(ME_KEY, res.user);
      router.replace(safeNext(params.get("next"), homeFor(res.user.role)));
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) setFormError("이메일 또는 비밀번호가 올바르지 않습니다");  // 어느 쪽이 틀렸는지 구분하지 않는다
        else if (e.status === 429) { const s = e.details["retry_after_sec"]; setFormError(`로그인 시도가 너무 많습니다. ${typeof s === "number" ? `${s}초 후` : "잠시 후"} 다시 시도해주세요`); }
        else if (e.code === "ACCOUNT_DISABLED") setFormError(e.message);
        else toast.error(e.message, { code: e.code, requestId: e.requestId });
      } else toast.error("네트워크 오류가 발생했습니다. 다시 시도해주세요");
      setFocus("password");
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="로그인">
      <div role="tablist" aria-label="로그인 역할" className="grid grid-cols-2 gap-1 rounded bg-surface-2 p-1">
        {ROLES.map((r) => (
          <button key={r.value} type="button" role="tab" aria-selected={role === r.value} onClick={() => setRole(r.value)}
            className={cn("h-9 rounded text-sm font-semibold transition", role === r.value ? "bg-surface shadow-sm" : "text-muted hover:text-text")}>{r.label}</button>
        ))}
      </div>
      <div>
        <label htmlFor="email" className="mb-1 block text-sm font-medium">이메일</label>
        <input id="email" type="email" autoComplete="username" aria-invalid={!!errors.email} aria-describedby={errors.email ? "email-err" : undefined}
          className="h-10 w-full rounded border border-border bg-surface px-3 text-sm" {...register("email")} />
        {errors.email && <p id="email-err" className="mt-1 text-xs text-danger">{errors.email.message}</p>}
      </div>
      <div>
        <label htmlFor="password" className="mb-1 block text-sm font-medium">비밀번호</label>
        <input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password}
          className="h-10 w-full rounded border border-border bg-surface px-3 text-sm" {...register("password")} />
        {errors.password && <p className="mt-1 text-xs text-danger">{errors.password.message}</p>}
      </div>
      {formError && <p role="alert" className="rounded bg-danger-bg px-3 py-2 text-sm text-danger">{formError}</p>}
      <Button type="submit" loading={isSubmitting} className="w-full">로그인</Button>
    </form>
  );
}
