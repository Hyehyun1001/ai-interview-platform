/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // 쿠키 인증(HttpOnly)이 동일 출처로 동작하도록 /api/v1 을 백엔드로 프록시한다. WebSocket 은 Next 가 프록시하지 못하므로
  // 브라우저가 NEXT_PUBLIC_WS_URL 로 백엔드에 직접 연결한다 (토큰은 쿼리의 1회용 단기 토큰, TRD §4.1).
  async rewrites() {
    const rules = [];
    rules.push({ source: "/api/v1/:path*", destination: `${BACKEND}/api/v1/:path*` });
    return rules;
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "same-origin" },
        // 카메라·마이크는 면접 화면에서만 필요하다 (self 로 한정)
        { key: "Permissions-Policy", value: "camera=(self), microphone=(self), geolocation=()" },
      ],
    }];
  },
};
export default nextConfig;
