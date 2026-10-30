export function Footer() {
  return (
    <footer className="mt-8 bg-brand-navy text-slate-400">
      <div className="mx-auto flex max-w-[1120px] flex-col gap-4 px-4 py-8 text-xs sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <p className="text-sm font-extrabold tracking-tight text-white">AuraEval <span className="text-accent">AI</span></p>
          <p>공정한 근거로 평가하는 AI 음성 면접</p>
          <p className="max-w-md leading-relaxed">음성·영상·이력서는 기업 서버 안에서만 저장·처리되며 외부 서비스로 전송되지 않습니다.</p>
        </div>
        <p className="font-medium text-slate-300">개인정보처리방침</p>
      </div>
    </footer>
  );
}
