import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, setSessionCookies } from "@/lib/auth-cookies";
import { API_BASE_URL, refreshTokens } from "@/lib/backend";

async function isAccessTokenValid(accessToken: string): Promise<boolean> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  return res.ok;
}

async function needsSetup(): Promise<boolean> {
  const res = await fetch(`${API_BASE_URL}/api/v1/setup/status`, { cache: "no-store" });
  if (!res.ok) return false;
  const data = await res.json().catch(() => ({ needs_setup: false }));
  return Boolean(data.needs_setup);
}

export async function middleware(request: NextRequest) {
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  if (!accessToken && !refreshToken) {
    if (await needsSetup()) {
      return NextResponse.redirect(new URL("/setup", request.url));
    }
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
    // Do NOT clear cookies here: a concurrent request (e.g. a client-side fetch through the
    // proxy route) may have already won the refresh race and rotated to a fresh, valid pair.
    // Clearing cookies on this "losing" response would wipe out that valid session. If the
    // session really is dead, the redirect below still sends the user to /login; the only
    // place that actively clears cookies is the explicit /api/auth/logout route.
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const forwardedHeaders = new Headers(request.headers);
  forwardedHeaders.set("cookie", `${ACCESS_COOKIE}=${rotated.access_token}; ${REFRESH_COOKIE}=${rotated.refresh_token}`);
  const response = NextResponse.next({ request: { headers: forwardedHeaders } });
  setSessionCookies(response, rotated.access_token, rotated.refresh_token);
  return response;
}

export const config = {
  matcher: ["/((?!login|setup|api|_next/static|_next/image|favicon.ico).*)"],
};
