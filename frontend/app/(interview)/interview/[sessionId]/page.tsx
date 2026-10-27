import { InterviewScreen } from "@/features/interview/interview-screen";

export default function InterviewPage({ params }: { params: { sessionId: string } }) {
  return <InterviewScreen sessionId={params.sessionId} />;
}
