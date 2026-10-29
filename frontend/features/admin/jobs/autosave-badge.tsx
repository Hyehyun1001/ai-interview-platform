import { cn } from "@/lib/utils";
import { autosaveLabel, type AutosaveInfo } from "./autosave";

/** 공고 작성 헤더의 자동 저장 상태. 실패하면 [지금 저장] 으로 바로 다시 시도할 수 있다. */
export function AutosaveBadge({ info }: { info: AutosaveInfo }) {
  const l = autosaveLabel(info);
  if (!l.text) return null;
  const tone = { muted: "text-muted", warning: "text-warning", danger: "text-danger", success: "text-success" }[l.tone];
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs", tone)} data-testid="autosave-status" data-phase={info.phase} data-dirty={info.dirty}>
      {l.text}
      {info.enabled && info.canSave && info.dirty && info.phase !== "saving" && info.phase !== "stale" && (
        <button type="button" onClick={() => void info.saveNow()} className="font-semibold underline" data-testid="autosave-now">지금 저장</button>
      )}
    </span>
  );
}
