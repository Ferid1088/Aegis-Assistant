import type { SessionEntitlements } from "@/types";
import {
  MessageSquareText, Search, FileText, Users2, Activity, ScrollText, Server,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  key: keyof SessionEntitlements["nav"];
  href: string;
  label: string;
  icon: LucideIcon;
}

// Full navigation. The shell filters this against session.nav so the user only
// sees surfaces they are entitled to (server still enforces on every request).
export const NAV_ITEMS: NavItem[] = [
  { key: "chat", href: "/chat", label: "Assistant", icon: MessageSquareText },
  { key: "search", href: "/search", label: "Search", icon: Search },
  { key: "documents", href: "/documents", label: "Documents", icon: FileText },
  { key: "admin", href: "/admin", label: "Admin", icon: Users2 },
  { key: "evaluation", href: "/evaluation", label: "Evaluation", icon: Activity },
  { key: "audit", href: "/audit", label: "Audit", icon: ScrollText },
  { key: "system", href: "/system", label: "System", icon: Server },
];
