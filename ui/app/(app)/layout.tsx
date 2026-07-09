import { AppShell } from "@/components/shell/app-shell";
import { getSession } from "@/lib/session";

export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  return <AppShell session={session}>{children}</AppShell>;
}
