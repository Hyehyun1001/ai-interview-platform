"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { ME_KEY, deleteAccount, fetchProfile, patchProfile } from "@/features/auth/api";

const PROFILE_KEY = ["me", "profile"] as const;
const PHONE = /^010-\d{4}-\d{4}$/;
const strong = (v: string) => v.length >= 8 && /[A-Za-z]/.test(v) && /\d/.test(v) && /[^A-Za-z0-9]/.test(v);
const input = "h-10 w-full rounded border border-border bg-surface px-3 text-sm";

/** 프로필 정보 탭: 이름·연락처 수정(생년월일·성별은 표시만), 비밀번호 변경, 회원 탈퇴·데이터 삭제 (UI_SPEC §4.4, NFR-S7). */
export function ProfileTab() {
  const q = useQuery({ queryKey: PROFILE_KEY, queryFn: fetchProfile, staleTime: 0 });
  if (q.isError) return <Card><ErrorState message="프로필을 불러오지 못했어요" onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
      <ProfileForm key={q.data.name + q.data.phone} name={q.data.name} phone={q.data.phone ?? ""} email={q.data.email} birth={q.data.birth_date ?? null} gender={q.data.gender ?? null} />
      <PasswordForm />
      <DeleteAccount />
    </div>
  );
}

const GENDER = { male: "남", female: "여", other: "기타" } as Record<string, string>;

function ProfileForm({ name, phone, email, birth, gender }: { name: string; phone: string; email: string; birth: string | null; gender: string | null }) {
  const qc = useQueryClient();
  const [n, setN] = useState(name);
  const [p, setP] = useState(phone);
  const phoneBad = p !== "" && !PHONE.test(p);
  const m = useMutation({
    mutationFn: () => patchProfile({ name: n.trim(), phone: p || null }),
    onSuccess: (r) => { toast.success("프로필을 저장했어요"); qc.setQueryData(PROFILE_KEY, r); void qc.invalidateQueries({ queryKey: ME_KEY }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "저장에 실패했어요"),
  });
  return (
    <Card className="space-y-3 p-5">
      <h2 className="font-bold">기본 정보</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">이름<input className={input} value={n} maxLength={50} onChange={(e) => setN(e.target.value)} /></label>
        <label className="text-sm">연락처<input className={input} value={p} placeholder="010-0000-0000" onChange={(e) => setP(e.target.value)} aria-invalid={phoneBad} />{phoneBad && <span className="text-xs text-danger">010-0000-0000 형식으로 입력하세요</span>}</label>
        <p className="text-sm">이메일<span className="mt-1 block text-muted">{email}</span></p>
        <p className="text-sm">생년월일 · 성별<span className="mt-1 block text-muted">{birth ?? "-"} · {gender ? (GENDER[gender] ?? gender) : "-"}</span></p>
      </div>
      <p className="text-xs text-muted">※ 생년월일·성별은 수정할 수 없으며 평가에 사용되지 않습니다.</p>
      <div className="flex justify-end"><Button onClick={() => m.mutate()} disabled={!n.trim() || phoneBad || (n === name && p === phone)} loading={m.isPending}>저장</Button></div>
    </Card>
  );
}

function PasswordForm() {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [cf, setCf] = useState("");
  const [curErr, setCurErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: () => patchProfile({ current_password: cur, new_password: nw }),
    onSuccess: () => { toast.success("비밀번호를 변경했어요"); setCur(""); setNw(""); setCf(""); setCurErr(null); },
    onError: (e) => { if (e instanceof ApiError && e.code === "WRONG_PASSWORD") setCurErr("현재 비밀번호가 일치하지 않습니다"); else toast.error(e instanceof ApiError ? e.message : "변경에 실패했어요"); },
  });
  const weak = nw !== "" && !strong(nw);
  const mismatch = cf !== "" && cf !== nw;
  return (
    <Card className="space-y-3 p-5">
      <h2 className="font-bold">비밀번호 변경</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">현재 비밀번호<input type="password" autoComplete="current-password" className={input} value={cur} onChange={(e) => { setCur(e.target.value); setCurErr(null); }} aria-invalid={!!curErr} />{curErr && <span role="alert" className="text-xs text-danger">{curErr}</span>}</label>
        <label className="text-sm">새 비밀번호<input type="password" autoComplete="new-password" className={input} value={nw} onChange={(e) => setNw(e.target.value)} aria-invalid={weak} />{weak && <span className="text-xs text-danger">8자 이상, 영문·숫자·특수문자를 포함하세요</span>}</label>
        <label className="text-sm">새 비밀번호 확인<input type="password" autoComplete="new-password" className={input} value={cf} onChange={(e) => setCf(e.target.value)} aria-invalid={mismatch} />{mismatch && <span className="text-xs text-danger">일치하지 않습니다</span>}</label>
      </div>
      <div className="flex justify-end"><Button onClick={() => m.mutate()} disabled={!cur || !strong(nw) || nw !== cf} loading={m.isPending}>비밀번호 변경</Button></div>
    </Card>
  );
}

function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();
  const qc = useQueryClient();
  useEffect(() => { if (open) { setPw(""); setErr(null); } }, [open]);
  const m = useMutation({
    mutationFn: () => deleteAccount(pw),
    onSuccess: () => { qc.clear(); toast.success("계정과 데이터를 삭제했어요"); router.replace("/login"); },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "WRONG_PASSWORD") setErr("비밀번호가 일치하지 않습니다");
      else if (e instanceof ApiError && e.code === "SESSION_IN_PROGRESS") setErr("진행 중인 면접이 있어 지금은 삭제할 수 없어요. 면접을 마친 뒤 다시 시도해 주세요.");
      else setErr(e instanceof ApiError ? e.message : "삭제에 실패했어요");
    },
  });
  return (
    <Card className="space-y-2 border-danger/40 p-5">
      <h2 className="font-bold text-danger">회원 탈퇴 · 데이터 삭제 요청</h2>
      <p className="text-sm text-muted">계정과 이력서, 면접 음성·영상, 리포트가 즉시 삭제되며 되돌릴 수 없어요.</p>
      <Button variant="danger" onClick={() => setOpen(true)} data-testid="delete-account">회원 탈퇴 · 데이터 삭제</Button>
      <Modal open={open} title="정말 삭제할까요?" onClose={() => { if (!m.isPending) setOpen(false); }}>
        <div className="space-y-3">
          <p className="text-sm">본인 확인을 위해 비밀번호를 다시 입력해 주세요.</p>
          <label className="block text-sm">비밀번호<input type="password" autoComplete="current-password" className={input} value={pw} onChange={(e) => { setPw(e.target.value); setErr(null); }} /></label>
          {err && <p role="alert" className="rounded bg-danger-bg p-2 text-sm text-danger">{err}</p>}
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setOpen(false)} disabled={m.isPending}>취소</Button><Button variant="danger" onClick={() => m.mutate()} disabled={!pw} loading={m.isPending}>삭제</Button></div>
        </div>
      </Modal>
    </Card>
  );
}
