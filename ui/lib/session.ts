import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ACCESS_COOKIE } from "@/lib/auth-cookies";
import type { SessionEntitlements } from "@/types";

const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

// Server-side session fetch, used by the authenticated layout on every
// request. middleware.ts already guarantees a valid, fresh access token
// before this runs; any failure here means the token was revoked between
// middleware and this call, or the backend is unreachable — either way,
// fail closed to /login rather than rendering a downgraded fake session.
export async function getSession(): Promise<SessionEntitlements> {
  const accessToken = cookies().get(ACCESS_COOKIE)?.value;
  if (!accessToken) redirect("/login");

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/session`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    redirect("/login");
  }
  if (!res.ok) redirect("/login");
  return (await res.json()) as SessionEntitlements;
}
