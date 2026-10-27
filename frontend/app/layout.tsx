import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = { title: { default: "AI Interview", template: "%s · AI Interview" }, description: "기업용 온프레미스 AI 모의면접 플랫폼" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="font-sans"><Providers>{children}</Providers></body>
    </html>
  );
}
