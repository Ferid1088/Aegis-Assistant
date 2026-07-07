"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-card border border-line bg-surface shadow-card", className)} {...props} />;
}

export function Eyebrow({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("text-eyebrow uppercase tracking-wider text-inkFaint", className)} {...props} />;
}

export function PageTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-6">
      <h1 className="font-display text-2xl text-ink">{children}</h1>
      {sub && <p className="mt-0.5 text-sm text-inkSoft">{sub}</p>}
    </div>
  );
}

type Tone = "neutral" | "accent" | "online" | "degraded" | "offline" | "info" | "role";
const toneMap: Record<Tone, string> = {
  neutral: "bg-surfaceMuted text-inkSoft",
  accent: "bg-accentWash text-accent",
  online: "bg-onlineWash text-online",
  degraded: "bg-accentWash text-degraded",
  offline: "bg-offlineWash text-offline",
  info: "bg-infoWash text-info",
  role: "bg-roleWash text-role",
};

export function Pill({ tone = "neutral", className, ...props }: { tone?: Tone } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[11px] font-medium", toneMap[tone], className)}
      {...props}
    />
  );
}

export function Mono({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("font-mono text-[13px] text-ink", className)} {...props} />;
}

export function Button({
  variant = "solid",
  className,
  ...props
}: { variant?: "solid" | "ghost" | "outline" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base = "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none";
  const variants = {
    solid: "bg-accent text-surface hover:bg-accentSoft",
    ghost: "text-inkSoft hover:bg-surfaceMuted",
    outline: "border border-line text-ink hover:bg-surfaceMuted",
    danger: "border border-offline/40 text-offline hover:bg-offlineWash",
  };
  return <button className={cn(base, variants[variant], className)} {...props} />;
}

export function StatusDot({ status }: { status: "online" | "degraded" | "offline" }) {
  const c = status === "online" ? "bg-online" : status === "degraded" ? "bg-degraded" : "bg-offline";
  return <span className={cn("inline-block h-1.5 w-1.5 rounded-full", c)} aria-hidden />;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-line bg-surface/50 px-6 py-16 text-center">
      <p className="font-display text-lg text-ink">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-sm text-inkSoft">{hint}</p>}
    </div>
  );
}
