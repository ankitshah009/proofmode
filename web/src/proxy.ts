import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Sets a nonce-based Content-Security-Policy on every page response.
 * Next.js reads the nonce from the request header and adds it to its own scripts.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const isHttps =
    request.nextUrl.protocol === "https:" || forwardedProto === "https";

  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' ${isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`}`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  // Only meaningful on https; on a plain http local run it would break asset loads in some browsers.
  if (isHttps) directives.push("upgrade-insecure-requests");
  const csp = directives.join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: the backend sets its own headers on the paths that are
      // forwarded to it, and static assets do not need a policy.
      source:
        "/((?!api/|_next/static|_next/image|favicon.ico|baseline.json|why.json|sample.png).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
