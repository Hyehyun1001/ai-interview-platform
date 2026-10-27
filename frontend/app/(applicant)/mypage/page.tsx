import type { Metadata } from "next";
import { ComingSoon } from "@/components/layout/coming-soon";

export const metadata: Metadata = { title: "마이페이지" };
export default function MyPage() {
  return <ComingSoon title="마이페이지" screenId="APP-04" />;
}
