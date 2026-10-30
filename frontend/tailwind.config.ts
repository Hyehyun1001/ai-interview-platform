import type { Config } from "tailwindcss";

// 디자인 토큰은 app/globals.css 의 CSS 변수로 정의한다 (UI_SPEC §3.3, A-4).
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--color-bg)", surface: "var(--color-surface)", "surface-2": "var(--color-surface-2)", border: "var(--color-border)",
        text: "var(--color-text)", muted: "var(--color-muted)", primary: "var(--color-primary)", accent: "var(--color-accent)", "accent-2": "var(--color-accent-2)", "brand-navy": "var(--color-brand-navy)", "primary-fg": "var(--color-primary-fg)",
        success: "var(--color-success)", warning: "var(--color-warning)", danger: "var(--color-danger)", info: "var(--color-info)",
        "success-bg": "var(--color-success-bg)", "warning-bg": "var(--color-warning-bg)", "danger-bg": "var(--color-danger-bg)",
        "info-bg": "var(--color-info-bg)",
      },
      borderRadius: { DEFAULT: "var(--radius)", lg: "var(--radius-lg)" },
      fontFamily: {
        // Pretendard 자체 호스팅 파일이 확정되면 next/font/local 로 교체한다 (UI_SPEC §3.3). 그 전에는 시스템 한글 폰트를 쓴다.
        sans: ["Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
