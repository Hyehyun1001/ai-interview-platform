import type { Metadata } from "next";
import { Suspense } from "react";
import { MyPageView } from "@/features/mypage/mypage-view";

export const metadata: Metadata = { title: "마이페이지" };
export default function MyPage() {
  return <Suspense fallback={null}><MyPageView /></Suspense>;
}
