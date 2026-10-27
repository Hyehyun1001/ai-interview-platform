"use client";
import { Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { makeChimeWav } from "./device-logic";

const GUIDE_TEXT = "안녕하세요. AI 면접관입니다. 이 소리가 들리면 들렸어요를 눌러 주세요.";

/**
 * 스피커 점검 (UI_SPEC §4.5.3). 로컬에서 만든 차임음을 재생하고(가능하면 브라우저 음성 안내를 이어서 읽는다), 사용자가 [들렸어요]를 눌러야 통과한다.
 * 출력 장치는 setSinkId 를 지원하는 브라우저에서만 고를 수 있다.
 */
export function SpeakerCheck({ outputId, active, passed, onPass }: { outputId?: string; active: boolean; passed: boolean; onPass: () => void }) {
  const [played, setPlayed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [heardNo, setHeardNo] = useState(false);
  const [playError, setPlayError] = useState(false);
  const urlRef = useRef<string | null>(null);
  const elRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => { elRef.current?.pause(); if (urlRef.current) URL.revokeObjectURL(urlRef.current); window.speechSynthesis?.cancel(); }, []);
  useEffect(() => { setPlayed(false); setHeardNo(false); }, [outputId]);  // 출력 장치를 바꾸면 다시 들어 봐야 한다

  async function play() {
    setPlayError(false);
    setHeardNo(false);
    urlRef.current ??= URL.createObjectURL(new Blob([makeChimeWav() as BlobPart], { type: "audio/wav" }));
    const el = (elRef.current ??= new Audio(urlRef.current));
    try {
      if (outputId && "setSinkId" in el) await (el as HTMLAudioElement & { setSinkId(id: string): Promise<void> }).setSinkId(outputId);
      el.currentTime = 0;
      setPlaying(true);
      el.onended = () => {
        setPlaying(false);
        try {
          if (window.speechSynthesis && typeof SpeechSynthesisUtterance !== "undefined") {
            const u = new SpeechSynthesisUtterance(GUIDE_TEXT);
            u.lang = "ko-KR";
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(u);
          }
        } catch { /* 음성 안내는 보조 — 차임음만으로도 점검할 수 있다 */ }
      };
      await el.play();
      setPlayed(true);
    } catch {
      setPlaying(false);
      setPlayError(true);
    }
  }

  if (!active && !passed) return <p className="text-sm text-muted">마이크 점검을 먼저 완료해 주세요.</p>;
  if (passed) return <p role="status" className="text-sm text-success">✅ 스피커 점검을 마쳤어요</p>;
  return (
    <div className="space-y-3" data-testid="speaker-check">
      <Button variant="secondary" onClick={() => void play()} loading={playing} data-testid="play-guide"><Play className="h-4 w-4" aria-hidden />안내 음성 재생</Button>
      {playError && <p role="alert" className="text-sm text-danger">소리를 재생하지 못했어요. 출력 장치를 확인하고 다시 눌러 주세요.</p>}
      {played && (
        <div className="space-y-2">
          <p className="text-sm font-medium">소리가 들렸나요?</p>
          <div className="flex gap-2">
            <Button onClick={onPass} data-testid="heard-yes">들렸어요</Button>
            <Button variant="secondary" onClick={() => setHeardNo(true)} data-testid="heard-no">안 들려요</Button>
          </div>
        </div>
      )}
      {heardNo && <p role="status" className="rounded bg-warning-bg p-2 text-sm text-warning" data-testid="heard-no-hint">기기의 볼륨과 음소거를 확인하거나 출력 장치를 바꾼 뒤 [안내 음성 재생]을 다시 눌러 주세요.</p>}
    </div>
  );
}
