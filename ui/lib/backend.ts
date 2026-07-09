export const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000";

export async function refreshTokens(
  refreshToken: string
): Promise<{ access_token: string; refresh_token: string } | null> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) return null;
  return res.json();
}
