"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ToastViewport } from "@/components/ui/toast-viewport";
import { ApiError } from "@/lib/api/client";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // 4xx(인증·권한·검증)는 재시도해도 같으므로 즉시 실패 처리, 네트워크/5xx 만 1회 재시도
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 1,
      },
    },
  }));
  return (
    <QueryClientProvider client={client}>
      {children}
      <ToastViewport />
    </QueryClientProvider>
  );
}
