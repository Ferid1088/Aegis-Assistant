"use client";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogOut, Search } from "lucide-react";
import { Button, Pill } from "@/components/ui/primitives";
import type { SessionEntitlements } from "@/types";

export function Topbar({ session }: { session: SessionEntitlements }) {
  const router = useRouter();

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <header className="flex h-12 items-center gap-4 border-b border-line bg-surface px-4">
      {session.nav.search && (
        <Link
          href="/search"
          className="flex h-8 max-w-md flex-1 items-center gap-2 rounded-md border border-line bg-canvas px-3 text-sm text-inkFaint hover:border-lineStrong"
        >
          <Search className="h-4 w-4" />
          <span>Search the corpus…</span>
        </Link>
      )}
      <div className="ml-auto flex items-center gap-3">
        <Pill tone="online">
          <span className="h-1.5 w-1.5 rounded-full bg-online" /> Air-gapped
        </Pill>
        <Pill tone="accent" className="capitalize">{session.edition}</Pill>
        <div className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-full bg-accentWash text-[11px] font-semibold text-accent">
            {session.user.name.slice(0, 1).toUpperCase()}
          </div>
          <div className="hidden leading-tight sm:block">
            <div className="text-[13px] font-medium text-ink">{session.user.name}</div>
            <div className="text-[11px] text-inkFaint">{session.user.role}</div>
          </div>
        </div>
        <Button variant="ghost" onClick={signOut} title="Sign out">
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
