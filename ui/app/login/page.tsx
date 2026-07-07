import { PageTitle } from "@/components/ui/primitives";

// Placeholder only: the real sign-in form (credentials + MFA) is Task 7's
// deliverable. This page exists so that middleware's redirect target
// (`/login`) resolves to a real 200 response instead of a 404 in the
// meantime — see Task 6 report for why this was added ahead of the brief's
// own file list.
export default function LoginPage() {
  return (
    <div className="grid h-screen place-items-center bg-canvas p-6">
      <PageTitle sub="The real sign-in form lands in Task 7.">Sign in to Aegis</PageTitle>
    </div>
  );
}
