import { describe, expect, it } from "vitest";
import { processSteps } from "@/features/jobs/job-view";
import { maxInterviewMinutes, toBullets } from "@/features/jobs/logic";

describe("공고 본문 → 항목", () => {
  it("줄 앞 기호(-, •, ·, *)를 떼고 빈 줄을 버린다", () => {
    expect(toBullets("- 주문 API 개발\n• 성능 개선\n·  장애 대응\n\n  * 모니터링  \r\n")).toEqual(["주문 API 개발", "성능 개선", "장애 대응", "모니터링"]);
  });
  it("기호가 없는 줄글은 줄 단위 항목, 비어 있으면 빈 배열", () => {
    expect(toBullets("Java 경험\nRedis 경험")).toEqual(["Java 경험", "Redis 경험"]);
    expect(toBullets(null)).toEqual([]);
    expect(toBullets("   \n \n")).toEqual([]);
  });
  it("HTML 은 해석하지 않고 그대로 문자열로 남긴다 (렌더 단계에서 텍스트로만 출력)", () => {
    expect(toBullets("- <img src=x onerror=alert(1)>")).toEqual(["<img src=x onerror=alert(1)>"]);
  });
});

describe("최대 면접 시간(답변 시간 기준 상한)", () => {
  it("질문 × (1 + 꼬리질문) × 답변 제한을 분으로 올림한다", () => {
    expect(maxInterviewMinutes(10, 2, 120)).toBe(60);
    expect(maxInterviewMinutes(10, 1, 60)).toBe(20);
    expect(maxInterviewMinutes(3, 0, 50)).toBe(3);
  });
  it("값이 없으면 null (추정치를 지어내지 않는다)", () => {
    expect(maxInterviewMinutes(null, 1, 60)).toBeNull();
    expect(maxInterviewMinutes(10, 1, null)).toBeNull();
    expect(maxInterviewMinutes(0, 1, 60)).toBeNull();
  });
});

describe("채용 절차", () => {
  const base = { codingEnabled: false, codingLimitSec: null, questionCount: 10, maxFollowups: 2, answerLimitSec: 60 };
  it("코딩테스트가 없으면 4단계, 있으면 면접 뒤에 코딩테스트가 들어간 5단계", () => {
    expect(processSteps(base).map((s) => s.title)).toEqual(["지원서 제출", "사전 환경 점검", "AI 음성 면접", "결과 확인"]);
    const withCoding = processSteps({ ...base, codingEnabled: true, codingLimitSec: 3600 });
    expect(withCoding.map((s) => s.title)).toEqual(["지원서 제출", "사전 환경 점검", "AI 음성 면접", "코딩테스트", "결과 확인"]);
    expect(withCoding[3]!.desc).toContain("제한시간 60분");
  });
  it("면접 단계에 질문 수와 꼬리질문 횟수를 알린다. 값이 없으면 숫자 없이 설명만", () => {
    expect(processSteps(base)[2]!.desc).toContain("질문 10개 + 꼬리질문 최대 2회");
    expect(processSteps({ ...base, questionCount: null, maxFollowups: null })[2]!.desc).not.toMatch(/\d/);
  });
});
