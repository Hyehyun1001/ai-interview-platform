import { beforeEach, describe, expect, it } from "vitest";
import { codingStartedAt, formatClock, loadDraft, remainingMs, saveDraft, verdictTone, VERDICT_LABEL } from "@/features/coding/coding-logic";
import { initialState, reduce, type InterviewState } from "@/features/interview/store";
import type { ServerMessage } from "@/features/interview/protocol";
import { STATUS_LABEL } from "@/features/jobs/logic";
import { signupSchema } from "@/features/auth/signup-modal";

const S = (over: Partial<InterviewState> = {}): InterviewState => ({ ...initialState, ...over });
const env = { seq: 1, ts: "2026-01-01T00:00:00Z" };
const codeQ = (turn: string, text = "복잡도는?"): ServerMessage =>
  ({ ...env, type: "question", turn_id: turn, turn_no: 3, kind: "code_followup", text, progress: { main: 2, total: 2 }, time_limit_sec: 60, tts: false, resumed: false });

describe("코드 꼬리질문 상태 전이 (채팅형, 음성 흐름을 건드리지 않는다)", () => {
  it("코딩 단계에서 질문이 오면 phase 는 그대로 두고 채팅·입력 대기만 갱신한다", () => {
    const s = S({ phase: "finished", finishedNext: "coding", codingActive: true });
    const p = reduce(s, codeQ("t1"), 1000);
    expect(p.phase).toBeUndefined();
    expect(p.codeQuestion).toEqual({ turnId: "t1", text: "복잡도는?", deadline: 61_000, limitSec: 60 });
    expect(p.codeChat).toEqual([{ role: "ai", text: "복잡도는?", turnId: "t1" }]);
    expect(p.question).toBeUndefined();  // 음성 질문 상태를 덮어쓰지 않는다
  });
  it("재접속으로 같은 질문이 다시 와도 채팅에 중복해서 쌓지 않는다", () => {
    const first = reduce(S(), codeQ("t1"), 0);
    const again = reduce(S({ codeChat: first.codeChat! }), codeQ("t1"), 5000);
    expect(again.codeChat).toHaveLength(1);
    expect(again.codeQuestion!.deadline).toBe(65_000);  // 남은 시간은 새로 받은 값
  });
  it("session_finished{coding} 은 코딩 화면을 켜고 대기 중인 질문을 닫는다 / done 은 켜지 않는다", () => {
    const pending = S({ codeQuestion: { turnId: "t1", text: "x", deadline: 1, limitSec: 1 } });
    expect(reduce(pending, { ...env, type: "session_finished", next: "coding" }, 0)).toMatchObject({ codingActive: true, codeQuestion: null, finishedNext: "coding", phase: "finished" });
    expect(reduce(S(), { ...env, type: "session_finished", next: "done" }, 0).codingActive).toBeUndefined();
  });
  it("음성 꼬리질문(followup)은 기존대로 phase 를 asking 으로 바꾼다", () => {
    const m: ServerMessage = { ...env, type: "question", turn_id: "v1", turn_no: 2, kind: "followup", text: "Redis?", progress: { main: 1, total: 2 }, time_limit_sec: 60, tts: true, resumed: false };
    expect(reduce(S({ phase: "thinking" }), m, 0).phase).toBe("asking");
  });
});

describe("코딩테스트 타이머·임시 저장", () => {
  beforeEach(() => sessionStorage.clear());
  it("남은 시간은 시작 시각 + 제한시간 기준이며 0 아래로 내려가지 않고, 제한이 없으면 null", () => {
    expect(remainingMs(1000, 60, 31_000)).toBe(30_000);
    expect(remainingMs(1000, 60, 999_999)).toBe(0);
    expect(remainingMs(1000, null, 5000)).toBeNull();
  });
  it("시작 시각은 처음 한 번만 기록되어 새로고침해도 이어진다", () => {
    expect(codingStartedAt("s1", 5000)).toBe(5000);
    expect(codingStartedAt("s1", 9000)).toBe(5000);
    expect(codingStartedAt("s2", 9000)).toBe(9000);
  });
  it("시계 표시는 올림하여 00:00 이 되기 전에 끝나지 않는다", () => {
    expect(formatClock(61_000)).toBe("01:01");
    expect(formatClock(100)).toBe("00:01");
    expect(formatClock(0)).toBe("00:00");
  });
  it("임시 저장은 세션·언어별로 분리된다", () => {
    saveDraft("s1", "python", "print(1)");
    expect(loadDraft("s1", "python")).toBe("print(1)");
    expect(loadDraft("s1", "java")).toBeNull();
    expect(loadDraft("s2", "python")).toBeNull();
  });
  it("판정 라벨은 7가지를 모두 가지고 AC 만 success 톤이다", () => {
    expect(Object.keys(VERDICT_LABEL).sort()).toEqual(["AC", "CE", "MLE", "OLE", "RE", "TLE", "WA"]);
    expect(verdictTone("AC")).toBe("success");
    expect(verdictTone("WA")).toBe("danger");
    expect(verdictTone("TLE")).toBe("warning");
  });
});

describe("회원가입 검증 (백엔드 RegisterRequest 와 같은 규칙)", () => {
  const ok = { name: "홍길동", email: "a@corp.local", password: "Passw0rd!", password_confirm: "Passw0rd!", birth_date: "1999/01/02", gender: "male", phone: "010-1234-5678" };
  it("올바른 입력은 통과, 사내 도메인(.local)도 허용", () => { expect(signupSchema.safeParse(ok).success).toBe(true); });
  it.each([
    [{ password: "abcdefgh", password_confirm: "abcdefgh" }, "영문, 숫자, 특수문자"],
    [{ password_confirm: "Different1!" }, "일치하지 않습니다"],
    [{ phone: "01012345678" }, "010-0000-0000"],
    [{ birth_date: "99/1/2" }, "YYYY/MM/DD"],
    [{ email: "no-at" }, "이메일 형식"],
  ])("거부: %j", (patch, msg) => {
    const r = signupSchema.safeParse({ ...ok, ...patch });
    expect(r.success).toBe(false);
    expect(JSON.stringify((r as { error: unknown }).error)).toContain(msg);
  });
});

describe("지원 현황 상태 라벨", () => {
  it("5개 상태를 모두 한국어 라벨로 가진다", () => { expect(Object.keys(STATUS_LABEL).sort()).toEqual(["applied", "interview_done", "interviewing", "prepared", "report_ready"]); });
});
