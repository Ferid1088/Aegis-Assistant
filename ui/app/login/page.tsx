"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, PageTitle } from "@/components/ui/primitives";

type Step = { kind: "credentials" } | { kind: "mfa"; pendingToken: string };

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>({ kind: "credentials" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) {
      setError(data.message || "Invalid username or password.");
      return;
    }
    if (data.mfa_required) {
      setStep({ kind: "mfa", pendingToken: data.mfa_pending_token });
      return;
    }
    router.push("/chat");
  }

  async function submitMfa(e: React.FormEvent) {
    e.preventDefault();
    if (step.kind !== "mfa") return;
    setError(null);
    setBusy(true);
    const res = await fetch("/api/auth/mfa-verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mfa_pending_token: step.pendingToken, totp_code: totpCode }),
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) {
      setError(data.message || "Invalid code.");
      return;
    }
    router.push("/chat");
  }

  return (
    <div className="grid h-screen place-items-center bg-canvas">
      <Card className="w-full max-w-sm p-6">
        <PageTitle sub="Air-gapped document intelligence">Sign in to Aegis</PageTitle>

        {step.kind === "credentials" && (
          <form onSubmit={submitCredentials} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
              Username
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </label>
            {error && <p className="text-sm text-offline">{error}</p>}
            <Button type="submit" disabled={busy || !username.trim() || !password.trim()}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        )}

        {step.kind === "mfa" && (
          <form onSubmit={submitMfa} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
              6-digit authenticator code
              <input
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
                autoFocus
                inputMode="numeric"
                maxLength={6}
              />
            </label>
            {error && <p className="text-sm text-offline">{error}</p>}
            <Button type="submit" disabled={busy || totpCode.trim().length !== 6}>
              {busy ? "Verifying…" : "Verify"}
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}
