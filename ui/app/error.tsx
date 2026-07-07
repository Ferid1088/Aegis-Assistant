"use client";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="grid h-full place-items-center">
      <div className="text-center">
        <p className="font-display text-lg text-ink">Something didn't load</p>
        <p className="mt-1 text-sm text-inkSoft">The service may be unreachable. Check the system status.</p>
        <button onClick={reset} className="mt-4 rounded-md bg-accent px-3 py-1.5 text-sm text-surface">Try again</button>
      </div>
    </div>
  );
}
