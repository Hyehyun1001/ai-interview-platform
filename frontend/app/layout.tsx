import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = { title: { default: "AuraEval AI", template: "%s · AuraEval AI" }, description: "격리형 엔터프라이즈 AI 채용 솔루션" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="font-sans"><Providers>{children}</Providers></body>
    </html>
  );
}
