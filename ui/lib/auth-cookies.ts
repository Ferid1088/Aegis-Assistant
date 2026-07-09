import { NextResponse } from "next/server";

export const ACCESS_COOKIE = "aegis_at";
export const REFRESH_COOKIE = "aegis_rt";
export const ACCESS_MAX_AGE = 900; // 15 min — matches settings.jwt_access_ttl_seconds
export const REFRESH_MAX_AGE = 1209600; // 14 days — matches settings.jwt_refresh_ttl_seconds

export const cookieOptions = {
  httpOnly: true,
  // NOTE: deliberately NOT `process.env.NODE_ENV === "production"` — Next.js's production
  // webpack build statically inlines NODE_ENV via DefinePlugin at build time (verified in the
  // compiled output: `secure:!0`), so a runtime env var can never flip it back off for a `next
  // start` process, even in local/integration-test environments that terminate plain HTTP.
  // COOKIE_SECURE is read at request time instead, so ops can opt out for environments where TLS
  // terminates in front of this process is not in play (defaults to secure, matching production).
  secure: process.env.COOKIE_SECURE !== "false",
  sameSite: "lax" as const,
  path: "/",
};

export function setSessionCookies(response: NextResponse, accessToken: string, refreshToken: string) {
  response.cookies.set(ACCESS_COOKIE, accessToken, { ...cookieOptions, maxAge: ACCESS_MAX_AGE });
  response.cookies.set(REFRESH_COOKIE, refreshToken, { ...cookieOptions, maxAge: REFRESH_MAX_AGE });
}

export function clearSessionCookies(response: NextResponse) {
  response.cookies.set(ACCESS_COOKIE, "", { ...cookieOptions, maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions, maxAge: 0 });
}
