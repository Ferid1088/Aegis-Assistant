"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Lock, Shield } from "lucide-react";
import type { ChatAnswer, ChatMessage, Citation, ConversationSummary } from "@/types";
import { api, ApiError } from "@/lib/api";
import { AnswerBlock } from "./answer-block";
import { ConversationList } from "./conversation-list";

interface RawMessageResponse {
  turnIndex: number;
  answer: string;
  citations: Citation[];
  verdict: ChatAnswer["verdict"];
  assumptions: string[];
  clarificationQuestion: string | null;
  unanswerableReason: string | null;
}

interface RawTurnResponse extends RawMessageResponse {
  question: string;
}

function toAnswer(raw: RawMessageResponse): ChatAnswer {
  return {
    verdict: raw.verdict,
    text: raw.answer,
    assumptions: raw.assumptions,
    clarificationQuestion: raw.clarificationQuestion ?? undefined,
    unanswerableReason: raw.unanswerableReason ?? undefined,
    citations: raw.citations,
  };
}

export function ChatView() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const activeConv = conversations.find((c) => c.id === conversationId) ?? null;
  const locked = activeConv?.locked ?? false;

  const loadConversations = useCallback(() => {
    api.get<ConversationSummary[]>("/conversations").then(setConversations).catch(() => {});
  }, []);
  useEffect(loadConversations, [loadConversations]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending]);

  async function openConversation(id: string) {
    setConversationId(id);
    try {
      const turns = await api.get<RawTurnResponse[]>(`/conversations/${id}/messages`);
      const opened: ChatMessage[] = turns.flatMap((t) => [
        { id: `${t.turnIndex}-q`, role: "user" as const, content: t.question },
        { id: `${t.turnIndex}-a`, role: "assistant" as const, content: t.answer, answer: toAnswer(t) },
      ]);
      setMessages(opened);
    } catch {
      setMessages([]);
    }
  }

  function newConversation() {
    setConversationId(null);
    setMessages([]);
    setInput("");
  }

  async function send(override?: string) {
    const q = (override ?? input).trim();
    if (!q || pending || locked) return;
    setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", content: q }]);
    setInput("");
    setPending(true);
    try {
      let id = conversationId;
      if (!id) {
        const conv = await api.post<{ id: string }>("/conversations");
        id = conv.id;
        setConversationId(id);
      }
      const raw = await api.post<RawMessageResponse>(`/conversations/${id}/messages`, { question: q });
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "assistant", content: raw.answer, answer: toAnswer(raw) }]);
      loadConversations();
    } catch (e) {
      const reason = e instanceof ApiError ? e.message : "The assistant is unreachable. Check the system status.";
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(), role: "assistant", content: "",
          answer: { verdict: "error", text: "", unanswerableReason: reason, citations: [] },
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex h-full">
      <ConversationList
        conversations={conversations}
        activeId={conversationId}
        onSelect={openConversation}
        onNew={newConversation}
      />

      <div className="mx-auto flex h-full max-w-3xl flex-1 flex-col">
        <div className="flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2 text-sm text-inkSoft">
            <Shield className="h-4 w-4 text-accent" />
            <span className="font-medium text-ink">{activeConv?.title ?? "New conversation"}</span>
            {locked && <span className="flex items-center gap-1 text-[12px] text-inkFaint"><Lock className="h-3 w-3" /> locked</span>}
          </div>
          <span className="rounded-pill border border-line px-2 py-0.5 text-[11px] text-inkFaint">Isolated session</span>
        </div>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-6 pb-4">
          {messages.length === 0 && (
            <div className="mt-24 text-center">
              <p className="font-display text-xl text-ink">Ask across your indexed corpus</p>
              <p className="mt-1 text-sm text-inkSoft">Answers are generated on-device and cite their sources. Nothing leaves this machine.</p>
            </div>
          )}
          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[80%] rounded-card bg-ink px-4 py-2.5 text-sm text-surface">{m.content}</div>
              </div>
            ) : (
              <div key={m.id} className="flex gap-3">
                <div className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accentWash text-accent">
                  <Shield className="h-3.5 w-3.5" />
                </div>
                <AnswerBlock
                  answer={m.answer!}
                  onCorrect={(correction) => { setInput(correction); send(correction); }}
                />
              </div>
            )
          )}
          {pending && (
            <div className="flex gap-3">
              <div className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accentWash text-accent">
                <Shield className="h-3.5 w-3.5" />
              </div>
              <div className="text-sm text-inkFaint">Searching the corpus…</div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div className="px-6 pb-6">
          {locked ? (
            <div className="rounded-card border border-line bg-surfaceMuted px-4 py-3 text-center text-[13px] text-inkSoft">
              This conversation is locked and can't receive new messages.
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-card border border-line bg-surface px-3 py-2 shadow-card">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Ask across your indexed corpus…"
                className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-inkFaint"
              />
              <button onClick={() => send()} disabled={pending} aria-label="Send" className="grid h-8 w-8 place-items-center rounded-md bg-ink text-surface disabled:opacity-40">
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          )}
          <p className="mt-2 text-center text-[11px] text-inkFaint">Responses generated entirely on-device. Nothing leaves this machine.</p>
        </div>
      </div>
    </div>
  );
}
