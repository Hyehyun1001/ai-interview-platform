"use client";
import type { ReactNode } from "react";

export function DeviceSelect({ label, devices, value, onChange, disabled }: { label: string; devices: MediaDeviceInfo[]; value?: string; onChange: (id: string) => void; disabled?: boolean }): ReactNode {
  if (devices.length === 0) return null;
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      <select value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} className="h-10 w-full rounded border border-border bg-surface px-2 text-sm">
        {!value && <option value="">기본 장치</option>}
        {devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `${label} ${i + 1}`}</option>)}
      </select>
    </label>
  );
}
