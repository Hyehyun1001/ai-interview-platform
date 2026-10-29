import { beforeEach, describe, expect, it } from "vitest";
import { autosaveLabel, clearNewJobBackup, readNewJobBackup, writeNewJobBackup } from "@/features/admin/jobs/autosave";

const base = { phase: "idle" as const, dirty: false, enabled: true, canSave: true, savedAt: null };

describe("autosaveLabel", () => {
  it("변경이 없고 저장 이력도 없으면 아무것도 보이지 않는다", () => expect(autosaveLabel(base).text).toBe(""));
  it("저장 직후에는 시각을 보여 준다", () => expect(autosaveLabel({ ...base, phase: "saved", savedAt: new Date(2026, 9, 29, 9, 5) }).text).toBe("자동 저장됨 09:05"));
  it("변경이 있으면 저장된 것처럼 보이지 않는다", () => {
    expect(autosaveLabel({ ...base, dirty: true, savedAt: new Date() }).text).toContain("저장되지 않은 변경 사항");
    expect(autosaveLabel({ ...base, dirty: true, enabled: false }).text).toBe("저장되지 않은 변경 사항이 있어요");
    expect(autosaveLabel({ ...base, dirty: true, canSave: false }).text).toContain("필수 입력");
  });
  it("저장 중·실패·충돌을 구분한다", () => {
    expect(autosaveLabel({ ...base, phase: "saving", dirty: true }).text).toBe("자동 저장 중…");
    expect(autosaveLabel({ ...base, phase: "error", dirty: true }).tone).toBe("danger");
    expect(autosaveLabel({ ...base, phase: "stale", dirty: true }).text).toContain("새로고침");
  });
});

describe("새 공고 백업", () => {
  beforeEach(() => localStorage.clear());
  it("쓰고 읽고 지운다", () => {
    expect(readNewJobBackup()).toBeNull();
    writeNewJobBackup({ title: "a" });
    expect(readNewJobBackup<{ title: string }>()?.form.title).toBe("a");
    clearNewJobBackup();
    expect(readNewJobBackup()).toBeNull();
  });
  it("깨진 값은 무시한다", () => { localStorage.setItem("ai-interview:job-draft:new", "{"); expect(readNewJobBackup()).toBeNull(); });
});
