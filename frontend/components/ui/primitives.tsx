import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg hover:opacity-90",
  secondary: "border border-border bg-surface text-text hover:bg-surface-2",
  ghost: "text-text hover:bg-surface-2",
  danger: "bg-danger text-white hover:opacity-90",
};

export function Button({ variant = "primary", loading, className, children, disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button {...rest} disabled={disabled || loading}
      className={cn("inline-flex h-10 items-center justify-center gap-2 rounded px-4 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50", VARIANT[variant], className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export const Card = ({ className, ...rest }: HTMLAttributes<HTMLDivElement>) =>
  <div {...rest} className={cn("rounded-lg border border-border bg-surface shadow-sm", className)} />;

type Tone = "neutral" | "success" | "warning" | "danger" | "info";
const TONE: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted", success: "bg-success-bg text-success", warning: "bg-warning-bg text-warning",
  danger: "bg-danger-bg text-danger", info: "bg-info-bg text-info",
};
/** 색만으로 의미를 전달하지 않도록 항상 텍스트(필요 시 아이콘)를 함께 둔다 (UI_SPEC §8). */
export const Badge = ({ tone = "neutral", className, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) =>
  <span {...rest} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold", TONE[tone], className)} />;

export const Skeleton = ({ className }: { className?: string }) =>
  <div aria-hidden className={cn("animate-pulse rounded bg-surface-2", className)} />;

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-4 py-8 text-center">
      <p className="font-semibold text-danger">{message ?? "데이터를 불러오지 못했어요"}</p>
      {onRetry && <Button variant="secondary" onClick={onRetry}>다시 시도</Button>}
    </div>
  );
}
