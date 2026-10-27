"use client";
import { create } from "zustand";

export type ToastKind = "success" | "info" | "warning" | "error";
export interface ToastItem { id: number; kind: ToastKind; message: string; code?: string; count: number; requestId?: string }

interface ToastState {
  items: ToastItem[];
  push: (kind: ToastKind, message: string, opts?: { code?: string; requestId?: string }) => void;
  dismiss: (id: number) => void;
}

const AUTO_CLOSE_MS: Record<ToastKind, number | null> = { success: 3000, info: 4000, warning: 6000, error: null };
const MAX_VISIBLE = 3;
let seq = 0;

export const useToastStore = create<ToastState>((set, get) => ({
  items: [],
  push: (kind, message, opts) => {
    const key = opts?.code ?? message;
    const dup = get().items.find((t) => (t.code ?? t.message) === key && t.kind === kind);
    if (dup) {
      // 같은 code 의 중복 Toast 는 병합하고 횟수만 올린다 (UI_SPEC §2.5)
      set({ items: get().items.map((t) => (t.id === dup.id ? { ...t, count: t.count + 1 } : t)) });
      return;
    }
    const id = ++seq;
    set({ items: [...get().items, { id, kind, message, code: opts?.code, requestId: opts?.requestId, count: 1 }].slice(-MAX_VISIBLE) });
    const ms = AUTO_CLOSE_MS[kind];
    if (ms) setTimeout(() => get().dismiss(id), ms);
  },
  dismiss: (id) => set({ items: get().items.filter((t) => t.id !== id) }),
}));

export const toast = {
  success: (m: string) => useToastStore.getState().push("success", m),
  info: (m: string) => useToastStore.getState().push("info", m),
  warning: (m: string, code?: string) => useToastStore.getState().push("warning", m, { code }),
  error: (m: string, opts?: { code?: string; requestId?: string }) => useToastStore.getState().push("error", m, opts),
};
