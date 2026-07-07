import { NextRequest, NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies, setSessionCookies } from "@/lib/auth-cookies";

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

type RouteContext = { params: { path: string[] } };

async function refreshTokens(refreshToken: string): Promise<{ access_token: string; refresh_token: string } | null> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) return null;
  return res.json();
}

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

  if (!accessToken) {
    return NextResponse.json({ code: "unauthorized", message: "no session" }, { status: 401 });
  }

  let backendRes = await forward(request, path, accessToken);

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
    const response = NextResponse.json({ code: "unauthorized", message: "session expired" }, { status: 401 });
    clearSessionCookies(response);
    return response;
  }

  const body = await backendRes.arrayBuffer();
  return passthrough(backendRes, body);
}

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST };
