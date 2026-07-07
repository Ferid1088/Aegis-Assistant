import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, setSessionCookies } from "@/lib/auth-cookies";

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

async function refreshTokens(refreshToken: string): Promise<{ access_token: string; refresh_token: string } | null> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) return null;
  return res.json();
}

async function isAccessTokenValid(accessToken: string): Promise<boolean> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  return res.ok;
}

export async function middleware(request: NextRequest) {
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  if (!accessToken && !refreshToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (accessToken && (await isAccessTokenValid(accessToken))) {
    return NextResponse.next();
  }

  if (!refreshToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const rotated = await refreshTokens(refreshToken);
  if (!rotated) {
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete(ACCESS_COOKIE);
    response.cookies.delete(REFRESH_COOKIE);
    return response;
  }

  const forwardedHeaders = new Headers(request.headers);
  forwardedHeaders.set("cookie", `${ACCESS_COOKIE}=${rotated.access_token}; ${REFRESH_COOKIE}=${rotated.refresh_token}`);
  const response = NextResponse.next({ request: { headers: forwardedHeaders } });
  setSessionCookies(response, rotated.access_token, rotated.refresh_token);
  return response;
}

export const config = {
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico).*)"],
};
