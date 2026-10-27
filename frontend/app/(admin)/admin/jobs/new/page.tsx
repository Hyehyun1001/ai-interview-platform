import { Suspense } from "react";
import { JobWizard } from "@/features/admin/jobs/job-wizard";

export default function Page() {
  return <Suspense><JobWizard /></Suspense>;
}
