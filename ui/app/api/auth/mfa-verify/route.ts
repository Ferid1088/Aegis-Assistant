import { NextRequest, NextResponse } from "next/server";
import { setSessionCookies } from "@/lib/auth-cookies";

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (!body?.mfa_pending_token || !body?.totp_code) {
    return NextResponse.json(
      { code: "bad_request", message: "mfa_pending_token and totp_code are required" },
      { status: 400 }
    );
  }

  const backendRes = await fetch(`${API_BASE_URL}/api/v1/auth/mfa/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_pending_token: body.mfa_pending_token, totp_code: body.totp_code }),
  });

  const data = await backendRes.json().catch(() => ({}));
  if (!backendRes.ok) {
    return NextResponse.json(data, { status: backendRes.status });
  }

  const response = NextResponse.json({ ok: true });
  setSessionCookies(response, data.access_token, data.refresh_token);
  return response;
}
