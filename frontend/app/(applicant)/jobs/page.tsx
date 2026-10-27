import type { Metadata } from "next";
import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "공고" };
export default function JobsPage() {
  return <ComingSoon title="공고 목록" screenId="APP-02" />;
}
