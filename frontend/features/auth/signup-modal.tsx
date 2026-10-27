"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { ME_KEY, register as registerApi } from "./api";

// 규칙은 백엔드(RegisterRequest)와 동일하게 유지한다. 최종 판단은 서버 응답이다.
export const signupSchema = z.object({
  name: z.string().trim().min(1, "이름을 입력하세요").max(50),
  email: z.string().trim().regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, "이메일 형식이 올바르지 않습니다"),
  password: z.string().min(8, "8자 이상 입력하세요").refine((v) => /[A-Za-z]/.test(v) && /\d/.test(v) && /[^A-Za-z0-9]/.test(v), "영문, 숫자, 특수문자를 모두 포함해야 합니다"),
  password_confirm: z.string(),
  birth_date: z.string().regex(/^\d{4}[/-]\d{2}[/-]\d{2}$/, "YYYY/MM/DD 형식으로 입력하세요"),
  gender: z.enum(["male", "female", "other"], { errorMap: () => ({ message: "성별을 선택하세요" }) }),
  phone: z.string().regex(/^010-\d{4}-\d{4}$/, "010-0000-0000 형식으로 입력하세요"),
}).refine((v) => v.password === v.password_confirm, { path: ["password_confirm"], message: "비밀번호가 일치하지 않습니다" });
type Values = z.infer<typeof signupSchema>;

const GENDERS = [["male", "남"], ["female", "여"], ["other", "기타"]] as const;

/** 회원가입 모달 (UI_SPEC §4.1.1). 성공하면 자동 로그인된 상태로 /jobs?welcome=1 로 이동해 APP-01b 팝업을 연다. */
export function SignupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { register, handleSubmit, setError, watch, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(signupSchema) });
  const [pw, pw2] = watch(["password", "password_confirm"]);
  // 객체 단위 refine 은 다른 필드 오류가 있으면 실행되지 않으므로 불일치는 입력 중에도 바로 보여 준다
  const mismatch = !!pw2 && pw !== pw2;

  const submit = handleSubmit(async (v) => {
    try {
      const res = await registerApi({ ...v, birth_date: v.birth_date.replace(/\//g, "-") });
      qc.setQueryData(ME_KEY, res.user);
      toast.success("가입이 완료되었습니다");
      router.replace("/jobs?welcome=1");
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === "EMAIL_ALREADY_EXISTS") { setError("email", { message: "이미 가입된 이메일입니다" }); return; }
        const fields = e.fieldErrors;
        if (e.status === 422 && fields.length) { fields.forEach((f) => setError(f.field.split(".").pop() as keyof Values, { message: f.message })); return; }
        toast.error(e.message, { code: e.code, requestId: e.requestId });
      } else toast.error("네트워크 오류가 발생했습니다. 다시 시도해주세요");
    }
  });

  const field = (name: keyof Values, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div>
      <label htmlFor={`su-${name}`} className="mb-1 block text-sm font-medium">{label} *</label>
      <input id={`su-${name}`} aria-invalid={!!errors[name]} className="h-10 w-full rounded border border-border bg-surface px-3 text-sm" {...register(name)} {...props} />
      {errors[name] && <p className="mt-1 text-xs text-danger">{errors[name]?.message}</p>}
      {name === "password_confirm" && mismatch && !errors[name] && <p className="mt-1 text-xs text-danger">비밀번호가 일치하지 않습니다</p>}
    </div>
  );

  return (
    <Modal open={open} title="회원가입" onClose={() => { if (!isSubmitting) onClose(); }}>
      <form onSubmit={submit} noValidate className="space-y-3" aria-label="회원가입">
        {field("name", "이름", { autoComplete: "name" })}
        {field("email", "이메일", { type: "email", autoComplete: "username" })}
        {field("password", "비밀번호", { type: "password", autoComplete: "new-password", placeholder: "8자+ 영문·숫자·특수문자" })}
        {field("password_confirm", "비밀번호 확인", { type: "password", autoComplete: "new-password" })}
        {field("birth_date", "생년월일", { placeholder: "YYYY/MM/DD", autoComplete: "bday" })}
        <fieldset>
          <legend className="mb-1 text-sm font-medium">성별 *</legend>
          <div className="flex gap-4 text-sm">{GENDERS.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="radio" value={v} {...register("gender")} />{l}</label>)}</div>
          {errors.gender && <p className="mt-1 text-xs text-danger">{errors.gender.message}</p>}
        </fieldset>
        {field("phone", "연락처", { placeholder: "010-0000-0000", autoComplete: "tel" })}
        <p className="text-xs text-muted">※ 생년월일·성별·연락처는 평가에 사용되지 않습니다.</p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>취소</Button>
          <Button type="submit" loading={isSubmitting}>가입하기</Button>
        </div>
      </form>
    </Modal>
  );
}
