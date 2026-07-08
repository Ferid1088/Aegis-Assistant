import { NextRequest, NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth-cookies";
import { API_BASE_URL } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (!body?.username || !body?.password) {
    return NextResponse.json({ code: "bad_request", message: "username and password are required" }, { status: 400 });
  }

  const setupRes = await fetch(`${API_BASE_URL}/api/v1/setup/admin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: body.username, password: body.password }),
  });
  const setupData = await setupRes.json().catch(() => ({}));
  if (!setupRes.ok) {
    return NextResponse.json(setupData, { status: setupRes.status });
  }

  const loginRes = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: body.username, password: body.password }),
  });
  const loginData = await loginRes.json().catch(() => ({}));
  if (!loginRes.ok) {
    return NextResponse.json(
      { code: "setup_login_failed", message: "admin account created, but automatic sign-in failed -- sign in manually" },
      { status: 500 },
    );
  }

  const response = NextResponse.json({ ok: true });
  setSessionCookies(response, loginData.access_token, loginData.refresh_token);
  return response;
}
