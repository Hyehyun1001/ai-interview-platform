import type { ReactNode } from "react";
import { AdminShell } from "@/components/layout/admin-shell";
import { AuthGuard } from "@/features/auth/auth-guard";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard allow={["recruiter", "admin"]}>
      <AdminShell>{children}</AdminShell>
    </AuthGuard>
  );
}
