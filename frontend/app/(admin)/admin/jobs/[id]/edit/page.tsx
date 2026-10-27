import { Suspense } from "react";
import { JobWizard } from "@/features/admin/jobs/job-wizard";

export default function Page({ params }: { params: { id: string } }) {
  return <Suspense><JobWizard jobId={params.id} /></Suspense>;
}
