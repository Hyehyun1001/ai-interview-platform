"use client";
import { useCallback, useEffect, useState } from "react";

export interface DeviceLists { video: MediaDeviceInfo[]; audio: MediaDeviceInfo[]; output: MediaDeviceInfo[] }
const EMPTY: DeviceLists = { video: [], audio: [], output: [] };

/** 장치 목록. 권한을 받기 전에는 label 이 비어 있으므로, 스트림 획득 뒤 refresh() 로 다시 읽는다. devicechange 로 자동 갱신된다. */
export function useDeviceList() {
  const [lists, setLists] = useState<DeviceLists>(EMPTY);
  const refresh = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setLists({ video: all.filter((d) => d.kind === "videoinput"), audio: all.filter((d) => d.kind === "audioinput"), output: all.filter((d) => d.kind === "audiooutput") });
    } catch { setLists(EMPTY); }
  }, []);
  useEffect(() => {
    void refresh();
    navigator.mediaDevices?.addEventListener?.("devicechange", refresh);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", refresh);
  }, [refresh]);
  return { lists, refresh };
}
