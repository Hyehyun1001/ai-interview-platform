import { redirect } from "next/navigation";

/** 마이페이지는 지원자 GNB 의 오른쪽 패널로 옮겼다. 예전 주소(`/mypage?tab=`)는 같은 탭이 열린 채로 공고 목록에 보낸다. */
export default function MyPage({ searchParams }: { searchParams: { tab?: string } }) {
  const tab = ["applications", "resume", "profile"].includes(searchParams.tab ?? "") ? searchParams.tab : "applications";
  redirect(`/jobs?mypage=${tab}`);
}
