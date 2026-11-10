import type { NextConfig } from "next";

// The Python backend is the single engine. The browser only calls same-origin
// paths, and these rewrites forward them to the backend. Rewrites are resolved
// when the app is built and when it starts, so set PROOFMODE_API_URL for both.
const backendOrigin = (
  process.env.PROOFMODE_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value:
      "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  experimental: {
    // An investigation can run for up to 120 seconds on the backend, so the
    // rewrite proxy must wait longer than that before giving up.
    proxyTimeout: 130_000,
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendOrigin}/api/:path*` },
      { source: "/baseline.json", destination: `${backendOrigin}/baseline.json` },
      { source: "/why.json", destination: `${backendOrigin}/why.json` },
      { source: "/sample.png", destination: `${backendOrigin}/sample.png` },
    ];
  },
  async headers() {
    // The Content-Security-Policy carries a fresh nonce per request, so it is
    // set in src/proxy.ts. The fixed headers below apply to every response.
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
