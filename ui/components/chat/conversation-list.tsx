"use client";
import * as React from "react";
import type { ConversationSummary } from "@/types";
import { Plus, Lock, MessageSquareText } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";

// Conversation history rail (5.5). Multi-turn threads are persisted server-side
// keyed by conversation id; locked threads accept no new turns.
export function ConversationList({
  conversations, activeId, onSelect, onNew,
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-eyebrow uppercase tracking-wider text-inkFaint">Conversations</span>
        <button onClick={onNew} className="grid h-6 w-6 place-items-center rounded-md text-inkSoft hover:bg-surfaceMuted hover:text-ink" aria-label="New conversation">
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {conversations.length === 0 && (
          <p className="px-2 py-6 text-center text-[12px] text-inkFaint">No conversations yet.</p>
        )}
        {conversations.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cn(
              "mb-1 flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition-colors",
              activeId === c.id ? "bg-accentWash" : "hover:bg-surfaceMuted"
            )}
          >
            <MessageSquareText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-inkFaint" />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1">
                <span className="truncate text-[13px] font-medium text-ink">{c.title || "Untitled"}</span>
                {c.locked && <Lock className="h-3 w-3 shrink-0 text-inkFaint" />}
              </span>
              <span className="text-[11px] text-inkFaint">{c.messageCount} messages · {formatDate(c.updatedAt)}</span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
