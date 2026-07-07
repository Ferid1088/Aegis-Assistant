import type { SessionEntitlements } from "@/types";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

// App shell: fixed rail + top bar, scrolling content. Server component wrapper;
// children are the routed pages.
export function AppShell({ session, children }: { session: SessionEntitlements; children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar session={session} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar session={session} />
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
