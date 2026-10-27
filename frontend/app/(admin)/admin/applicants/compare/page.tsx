import { Suspense } from "react";
import { CompareView } from "@/features/admin/compare/compare-view";

export default function Page() {
  return <Suspense><CompareView /></Suspense>;
}
