import { EmptyState } from "@/components/ui/primitives";

/** Phase 3 범위 밖 화면의 자리 표시. 내비게이션이 404 로 끊기지 않게 하며, 구현된 기능으로 오해되지 않도록 문구를 분명히 한다. */
export function ComingSoon({ title, screenId }: { title: string; screenId: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface">
      <EmptyState title={`${title} — 아직 구현되지 않았습니다`} description={`화면 ID ${screenId}. docs/UI_SPEC.md 의 후속 개발 단계에서 구현합니다.`} />
    </div>
  );
}
