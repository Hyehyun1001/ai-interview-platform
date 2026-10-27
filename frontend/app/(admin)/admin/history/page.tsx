import type { Metadata } from "next";
import { Suspense } from "react";
import { HistoryView } from "@/features/admin/history/history-view";

export const metadata: Metadata = { title: "이력·알림" };
export default function Page() {
  return <Suspense fallback={null}><HistoryView /></Suspense>;
}
