"use client";
import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, FileText, HelpCircle, Info, Pencil } from "lucide-react";
import type { ChatAnswer } from "@/types";
import { Pill } from "@/components/ui/primitives";

export function AnswerBlock({ answer, onCorrect }: { answer: ChatAnswer; onCorrect?: (correction: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [correction, setCorrection] = useState("");

  return (
    <div className="max-w-[80%] space-y-3">
      {answer.verdict === "clarification" ? (
        <Callout tone="info" icon={<HelpCircle className="h-4 w-4" />} title="Needs a detail">
          {answer.clarificationQuestion}
        </Callout>
      ) : answer.verdict === "unanswerable" ? (
        <Callout tone="offline" icon={<AlertTriangle className="h-4 w-4" />} title="Can't answer from your sources">
          {answer.unanswerableReason}
        </Callout>
      ) : (
        <>
          {answer.verdict === "assumption" && answer.assumptions?.length ? (
            <Callout tone="degraded" icon={<Info className="h-4 w-4" />} title="Answered under an assumption">
              <ul className="list-disc pl-4">{answer.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
              {onCorrect && (
                editing ? (
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      value={correction}
                      onChange={(e) => setCorrection(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && correction.trim() && (onCorrect(correction), setEditing(false))}
                      placeholder="Correct the assumption…"
                      className="flex-1 rounded-md border border-line bg-canvas px-2 py-1 text-[13px] outline-none focus:border-accent"
                      autoFocus
                    />
                    <button
                      onClick={() => { if (correction.trim()) { onCorrect(correction); setEditing(false); } }}
                      className="rounded-md bg-accent px-2 py-1 text-[12px] text-surface"
                    >
                      Re-run
                    </button>
                  </div>
                ) : (
                  <button onClick={() => setEditing(true)} className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
                    <Pencil className="h-3 w-3" /> Correct this
                  </button>
                )
              )}
            </Callout>
          ) : null}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{answer.text}</p>
        </>
      )}

      {answer.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {answer.citations.map((c, i) => (
            (() => {
              const region = c.region
                ? `${c.region[0]},${c.region[1]},${c.region[0] + c.region[2]},${c.region[1] + c.region[3]}`
                : null;
              const href = `/viewer/${c.documentId}?v=${c.versionNo}&page=${c.page}${region ? `&region=${region}` : ""}`;
              return (
                <Link
                  key={i}
                  href={href}
                  className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 font-mono text-[11px] text-inkSoft hover:border-lineStrong hover:text-ink"
                >
                  <FileText className="h-3 w-3" />{c.documentTitle}<span className="text-inkFaint">· p.{c.page}</span>
                </Link>
              );
            })()
          ))}
        </div>
      )}
    </div>
  );
}

function Callout({ tone, icon, title, children }: { tone: "info" | "offline" | "degraded"; icon: React.ReactNode; title: string; children: React.ReactNode }) {
  const border = tone === "info" ? "border-info/30" : tone === "offline" ? "border-offline/30" : "border-accent/30";
  const text = tone === "info" ? "text-info" : tone === "offline" ? "text-offline" : "text-degraded";
  return (
    <div className={`rounded-card border ${border} bg-surface p-3`}>
      <div className={`mb-1 flex items-center gap-1.5 text-[13px] font-medium ${text}`}>{icon} {title}</div>
      <div className="text-sm text-ink">{children}</div>
    </div>
  );
}
