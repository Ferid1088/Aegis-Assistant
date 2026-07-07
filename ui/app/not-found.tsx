import Link from "next/link";
export default function NotFound() {
  return (
    <div className="grid h-full place-items-center">
      <div className="text-center">
        <p className="font-display text-lg text-ink">Page not found</p>
        <Link href="/chat" className="mt-3 inline-block text-sm text-accent hover:underline">Back to the assistant</Link>
      </div>
    </div>
  );
}
