import { redirect } from "next/navigation";
import { API_BASE_URL } from "@/lib/backend";
import { SetupForm } from "./setup-form";

export default async function SetupPage() {
  const res = await fetch(`${API_BASE_URL}/api/v1/setup/status`, { cache: "no-store" });
  const data = await res.json().catch(() => ({ needs_setup: false }));
  if (!data.needs_setup) {
    redirect("/login");
  }
  return <SetupForm />;
}
