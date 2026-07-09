import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, setSessionCookies } from "@/lib/auth-cookies";
import { API_BASE_URL, refreshTokens } from "@/lib/backend";

type RouteContext = { params: { path: string[] } };

async function forward(request: NextRequest, path: string[], accessToken: string): Promise<Response> {
  const url = `${API_BASE_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("authorization", `Bearer ${accessToken}`);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  return fetch(url, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
  });
}

function passthrough(backendRes: Response, body: ArrayBuffer): NextResponse {
  const headers = new Headers();
  const contentType = backendRes.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  return new NextResponse(body, { status: backendRes.status, headers });
}

async function handle(request: NextRequest, context: RouteContext) {
  const path = context.params.path;
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  if (!accessToken && !refreshToken) {
    return NextResponse.json({ code: "unauthorized", message: "no session" }, { status: 401 });
  }

  // Access-token cookie's 15 min Max-Age can lapse (browser stops sending it) well before the
  // refresh token does -- fall straight to the refresh path below instead of a doomed forward().
  let backendRes = accessToken
    ? await forward(request, path, accessToken)
    : new Response(null, { status: 401 });

  if (backendRes.status === 401 && refreshToken) {
    const rotated = await refreshTokens(refreshToken);
    if (rotated) {
      backendRes = await forward(request, path, rotated.access_token);
      const body = await backendRes.arrayBuffer();
      const response = passthrough(backendRes, body);
      setSessionCookies(response, rotated.access_token, rotated.refresh_token);
      return response;
    }
  }

  if (backendRes.status === 401) {
    // Do NOT clear cookies here: a concurrent request (e.g. a page navigation handled by
    // middleware.ts) may have already won the refresh race and rotated to a fresh, valid pair.
    // Clearing cookies on this "losing" response would wipe out that valid session. If the
    // session really is dead, the 401 below still bounces the client to /login; the only place
    // that actively clears cookies is the explicit /api/auth/logout route.
    return NextResponse.json({ code: "unauthorized", message: "session expired" }, { status: 401 });
  }

  const body = await backendRes.arrayBuffer();
  return passthrough(backendRes, body);
}

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST };
