"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Shield } from "lucide-react";
import { NAV_ITEMS } from "@/lib/nav";
import type { SessionEntitlements } from "@/types";
import { cn } from "@/lib/utils";
import { ThemeSwitcher } from "./theme-switcher";

export function Sidebar({ session }: { session: SessionEntitlements }) {
  const pathname = usePathname();
  const items = NAV_ITEMS.filter((i) => session.nav[i.key]); // permission-aware

  return (
    <aside className="flex w-14 flex-col items-center border-r border-line bg-surface py-3">
      <Link href="/chat" className="mb-4 grid h-9 w-9 place-items-center rounded-md bg-ink text-surface" aria-label="Aegis home">
        <Shield className="h-4 w-4" />
      </Link>

      <nav className="flex flex-1 flex-col items-center gap-1">
        {items.map((item) => {
          const active = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.key}
              href={item.href}
              title={item.label}
              aria-current={active ? "page" : undefined}
              className={cn(
                "grid h-9 w-9 place-items-center rounded-md text-inkFaint transition-colors hover:bg-surfaceMuted hover:text-ink",
                active && "bg-accentWash text-accent"
              )}
            >
              <Icon className="h-[18px] w-[18px]" />
            </Link>
          );
        })}
      </nav>

      {/* color-dot theme switcher — recolors the whole UI on click */}
      <ThemeSwitcher />

      <div className="vertical-rl mt-2 select-none text-[9px] uppercase tracking-[0.2em] text-inkFaint">
        Air-gapped
      </div>
    </aside>
  );
}
