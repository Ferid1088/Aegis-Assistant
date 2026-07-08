"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shield } from "lucide-react";
import { Button, Card } from "@/components/ui/primitives";

const MIN_PASSWORD_LENGTH = 12;

export function SetupForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const passwordLongEnough = password.length >= MIN_PASSWORD_LENGTH;
  const passwordsMatch = password.length > 0 && password === confirmPassword;
  const canSubmit = username.trim().length > 0 && passwordLongEnough && passwordsMatch && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    const res = await fetch("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) {
      if (res.status === 409) {
        router.replace("/login");
        return;
      }
      setError(data.message || "Could not create the admin account.");
      return;
    }
    router.push("/chat");
  }

  return (
    <div className="grid h-screen place-items-center bg-canvas">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-ink text-surface"><Shield className="h-4 w-4" /></div>
          <div>
            <div className="font-display text-lg text-ink">Aegis setup</div>
            <div className="text-[12px] text-inkFaint">Air-gapped · runs entirely on this machine</div>
          </div>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
            Admin username
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
            <span className={passwordLongEnough ? "text-online" : "text-inkFaint"}>
              {password.length}/{MIN_PASSWORD_LENGTH} characters minimum
            </span>
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-inkSoft">
            Confirm password
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </label>
          {error && <p className="text-sm text-offline">{error}</p>}
          <Button type="submit" disabled={!canSubmit}>
            {busy ? "Creating account…" : "Create admin account"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
