import { NextResponse } from "next/server";

export const ACCESS_COOKIE = "aegis_at";
export const REFRESH_COOKIE = "aegis_rt";
export const ACCESS_MAX_AGE = 900; // 15 min — matches settings.jwt_access_ttl_seconds
export const REFRESH_MAX_AGE = 1209600; // 14 days — matches settings.jwt_refresh_ttl_seconds

export const cookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
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
