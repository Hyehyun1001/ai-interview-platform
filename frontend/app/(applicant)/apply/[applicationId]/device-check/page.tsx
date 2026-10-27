import type { Metadata } from "next";
import { DeviceCheckClient } from "@/features/device-check/device-check-client";

export const metadata: Metadata = { title: "사전 환경 점검" };
export default function DeviceCheckPage({ params }: { params: { applicationId: string } }) {
  return <DeviceCheckClient applicationId={params.applicationId} />;
}
