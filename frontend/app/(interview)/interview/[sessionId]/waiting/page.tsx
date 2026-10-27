import { WaitingView } from "@/features/report/waiting-view";

export default function Page({ params }: { params: { sessionId: string } }) {
  return <WaitingView sessionId={params.sessionId} />;
}
