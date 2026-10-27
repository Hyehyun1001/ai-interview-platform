"use client";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LogOut, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { logout, useMe } from "@/features/auth/api";
import { toast } from "@/lib/toast";

export function UserMenu() {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const qc = useQueryClient();

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const onLogout = async () => {
    try { await logout(); } catch { /* 이미 만료된 세션이어도 로컬 상태는 정리한다 */ }
    qc.clear();
    toast.info("로그아웃되었습니다");
    router.replace("/login");
  };

  return (
    <div ref={ref} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex h-9 items-center gap-1.5 rounded px-2 text-sm hover:bg-surface-2">
        <User className="h-4 w-4" aria-hidden /><span className="max-w-[8rem] truncate">{me?.name ?? "…"}</span><ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-44 rounded border border-border bg-surface py-1 shadow-lg">
          {me && <p className="truncate px-3 py-1.5 text-xs text-muted">{me.email}</p>}
          <button role="menuitem" type="button" onClick={onLogout} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2">
            <LogOut className="h-4 w-4" aria-hidden />로그아웃
          </button>
        </div>
      )}
    </div>
  );
}
