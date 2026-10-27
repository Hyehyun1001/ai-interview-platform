"use client";
import { Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useFieldArray, type UseFormReturn } from "react-hook-form";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { BasicInfoIssues, ResumeFormValues } from "./schema";

const inputCls = "h-10 w-full rounded border border-border bg-surface px-3 text-sm disabled:bg-surface-2 disabled:text-muted";
const invalidCls = "border-danger ring-1 ring-danger";

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return <label className="block space-y-1 text-sm"><span className="font-medium">{label}{required && <span className="text-danger" aria-hidden> *</span>}</span>{children}</label>;
}

function SkillChips({ label, values, onChange, disabled }: { label: string; values: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !values.includes(t)) onChange([...values, t]);
    setText("");
  };
  return (
    <div className="space-y-2">
      <span className="text-sm font-medium">{label}</span>
      <ul className="flex flex-wrap gap-2" aria-label={`${label} 목록`}>
        {values.map((v) => (
          <li key={v} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-3 py-1 text-sm">
            {v}
            {!disabled && <button type="button" aria-label={`${v} 삭제`} onClick={() => onChange(values.filter((x) => x !== v))}><X className="h-3.5 w-3.5" aria-hidden /></button>}
          </li>
        ))}
      </ul>
      {!disabled && (
        <div className="flex gap-2">
          <input aria-label={`${label} 입력`} value={text} onChange={(e) => setText(e.target.value)} className={inputCls} maxLength={60}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
          <Button type="button" variant="secondary" onClick={add}>추가</Button>
        </div>
      )}
    </div>
  );
}

/**
 * 이력서 입력 폼 (UI_SPEC §4.3.2). 마이페이지(APP-04)·가입 팝업(APP-01b)·지원 단계(APP-05)가 함께 쓴다.
 * 필수는 성명과 (학력 또는 경력 1건 이상)뿐이며 자소서는 선택이다. readOnly 면 모든 입력이 비활성화된다.
 */
export function ResumeEditor({ form, readOnly = false, issues }: { form: UseFormReturn<ResumeFormValues>; readOnly?: boolean; issues?: BasicInfoIssues | null }) {
  const { register, control, watch, setValue } = form;
  const edu = useFieldArray({ control, name: "education" });
  const exp = useFieldArray({ control, name: "experience" });
  const prj = useFieldArray({ control, name: "projects" });
  const careerBad = !!issues?.career;

  return (
    <fieldset disabled={readOnly} className="space-y-6" data-testid="resume-editor">
      <legend className="sr-only">이력서 정보</legend>

      <Field label="성명" required>
        <input {...register("name")} aria-invalid={!!issues?.name} className={cn(inputCls, issues?.name && invalidCls)} maxLength={50} autoComplete="off" />
        {issues?.name && <span role="alert" className="text-xs text-danger">성명을 입력해 주세요.</span>}
      </Field>

      <section className="space-y-3" aria-labelledby="edu-h">
        <div className="flex items-center justify-between">
          <h3 id="edu-h" className="font-bold">학력 <span className="text-danger" aria-hidden>*</span></h3>
          {!readOnly && <Button type="button" variant="secondary" onClick={() => edu.append({ school: "", major: "", degree: "", start: "", end: "" })}><Plus className="h-4 w-4" aria-hidden />학력 추가</Button>}
        </div>
        {edu.fields.map((f, i) => (
          <div key={f.id} className="grid gap-2 rounded border border-border p-3 sm:grid-cols-5">
            <Field label="학교명"><input {...register(`education.${i}.school`)} aria-label={`학교명 ${i + 1}`} aria-invalid={careerBad} className={cn(inputCls, careerBad && invalidCls)} /></Field>
            <Field label="전공"><input {...register(`education.${i}.major`)} aria-label={`전공 ${i + 1}`} className={inputCls} /></Field>
            <Field label="학위"><input {...register(`education.${i}.degree`)} aria-label={`학위 ${i + 1}`} className={inputCls} /></Field>
            <Field label="시작"><input {...register(`education.${i}.start`)} aria-label={`학력 시작 ${i + 1}`} placeholder="2019.03" className={inputCls} /></Field>
            <div className="flex items-end gap-2">
              <Field label="종료"><input {...register(`education.${i}.end`)} aria-label={`학력 종료 ${i + 1}`} placeholder="2023.02" className={inputCls} /></Field>
              {!readOnly && edu.fields.length > 1 && <Button type="button" variant="ghost" aria-label={`학력 ${i + 1} 삭제`} onClick={() => edu.remove(i)}><Trash2 className="h-4 w-4" aria-hidden /></Button>}
            </div>
          </div>
        ))}
      </section>

      <section className="space-y-3" aria-labelledby="exp-h">
        <div className="flex items-center justify-between">
          <h3 id="exp-h" className="font-bold">경력</h3>
          {!readOnly && <Button type="button" variant="secondary" onClick={() => exp.append({ company: "", role: "", start: "", end: "", summary: "" })}><Plus className="h-4 w-4" aria-hidden />경력 추가</Button>}
        </div>
        {exp.fields.length === 0 && <p className="text-sm text-muted">경력이 없으면 비워 두세요. (학력 또는 경력 중 1건 이상 필요)</p>}
        {exp.fields.map((f, i) => (
          <div key={f.id} className="grid gap-2 rounded border border-border p-3 sm:grid-cols-4">
            <Field label="회사명"><input {...register(`experience.${i}.company`)} aria-label={`회사명 ${i + 1}`} aria-invalid={careerBad} className={cn(inputCls, careerBad && invalidCls)} /></Field>
            <Field label="직무"><input {...register(`experience.${i}.role`)} aria-label={`직무 ${i + 1}`} className={inputCls} /></Field>
            <Field label="시작"><input {...register(`experience.${i}.start`)} aria-label={`경력 시작 ${i + 1}`} placeholder="2023.03" className={inputCls} /></Field>
            <div className="flex items-end gap-2">
              <Field label="종료"><input {...register(`experience.${i}.end`)} aria-label={`경력 종료 ${i + 1}`} placeholder="현재" className={inputCls} /></Field>
              {!readOnly && <Button type="button" variant="ghost" aria-label={`경력 ${i + 1} 삭제`} onClick={() => exp.remove(i)}><Trash2 className="h-4 w-4" aria-hidden /></Button>}
            </div>
            <div className="sm:col-span-4"><Field label="업무 요약"><input {...register(`experience.${i}.summary`)} aria-label={`업무 요약 ${i + 1}`} className={inputCls} /></Field></div>
          </div>
        ))}
      </section>
      {careerBad && <p role="alert" className="text-sm text-danger" data-testid="career-issue">학력(학교명) 또는 경력(회사명)을 1건 이상 입력해 주세요.</p>}

      <section className="space-y-3" aria-labelledby="prj-h">
        <div className="flex items-center justify-between">
          <h3 id="prj-h" className="font-bold">프로젝트</h3>
          {!readOnly && <Button type="button" variant="secondary" onClick={() => prj.append({ title: "", role: "", period: "", tech_stack: "", description: "" })}><Plus className="h-4 w-4" aria-hidden />프로젝트 추가</Button>}
        </div>
        {prj.fields.map((f, i) => (
          <div key={f.id} className="grid gap-2 rounded border border-border p-3 sm:grid-cols-3">
            <Field label="제목"><input {...register(`projects.${i}.title`)} aria-label={`프로젝트 제목 ${i + 1}`} className={inputCls} /></Field>
            <Field label="역할"><input {...register(`projects.${i}.role`)} aria-label={`프로젝트 역할 ${i + 1}`} className={inputCls} /></Field>
            <div className="flex items-end gap-2">
              <Field label="기간"><input {...register(`projects.${i}.period`)} aria-label={`프로젝트 기간 ${i + 1}`} className={inputCls} /></Field>
              {!readOnly && <Button type="button" variant="ghost" aria-label={`프로젝트 ${i + 1} 삭제`} onClick={() => prj.remove(i)}><Trash2 className="h-4 w-4" aria-hidden /></Button>}
            </div>
            <div className="sm:col-span-3"><Field label="기술 스택 (쉼표로 구분)"><input {...register(`projects.${i}.tech_stack`)} aria-label={`기술 스택 ${i + 1}`} className={inputCls} /></Field></div>
            <div className="sm:col-span-3"><Field label="설명"><textarea {...register(`projects.${i}.description`)} aria-label={`프로젝트 설명 ${i + 1}`} rows={2} className={cn(inputCls, "h-auto py-2")} /></Field></div>
          </div>
        ))}
      </section>

      <SkillChips label="기술" values={watch("skills")} onChange={(v) => setValue("skills", v, { shouldDirty: true })} disabled={readOnly} />
      <SkillChips label="자격" values={watch("certifications")} onChange={(v) => setValue("certifications", v, { shouldDirty: true })} disabled={readOnly} />

      <Field label="자기소개서 (선택)">
        <textarea {...register("self_intro")} rows={5} maxLength={5000} className={cn(inputCls, "h-auto py-2")} />
      </Field>
    </fieldset>
  );
}
