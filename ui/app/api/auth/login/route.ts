import { NextRequest, NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth-cookies";

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (!body?.username || !body?.password) {
    return NextResponse.json({ code: "bad_request", message: "username and password are required" }, { status: 400 });
  }

  const backendRes = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: body.username, password: body.password }),
  });

  const data = await backendRes.json().catch(() => ({}));
  if (!backendRes.ok) {
    return NextResponse.json(data, { status: backendRes.status });
  }

  if (data.mfa_required) {
    return NextResponse.json({ mfa_required: true, mfa_pending_token: data.mfa_pending_token });
  }

  const response = NextResponse.json({ ok: true });
  setSessionCookies(response, data.access_token, data.refresh_token);
  return response;
}
