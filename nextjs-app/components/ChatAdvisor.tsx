"use client";

import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";
import { safeExternalUrl } from "@/lib/chartData";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Send, AlertTriangle, RotateCcw } from "lucide-react";

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations?: { text: string; source: string; url?: string }[];
  provider?: string;
  model?: string;
  failed?: boolean;
}

interface Props {
  symbol: string;
}

let nextMessageId = 1;

export default function ChatAdvisor({ symbol }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: nextMessageId++,
      role: "assistant",
      content: `Ask me anything about ${symbol}. I will ground my answer in real company filings, news, and price data — and cite every source.`,
    },
  ]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: providersData } = useQuery({
    queryKey: ["providers"],
    queryFn: () => stockApi.getProviders().then((r) => r.data),
    staleTime: Infinity,
  });

  // Initialize selected provider to the server default once it loads.
  useEffect(() => {
    if (providersData?.default && !provider) {
      setProvider(providersData.default);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providersData]);

  const availableProviders = providersData?.available || {};
  const modelNames: { anthropic?: string; gemini?: string } = providersData?.models || {};
  const providerOptions = [
    { key: "anthropic", label: modelNames.anthropic || "Anthropic" },
    { key: "gemini", label: modelNames.gemini || "Gemini" },
  ].filter((p) => availableProviders[p.key as keyof typeof availableProviders]);

  const send = (message: string) => {
    setMessages((prev) => [
      ...prev,
      { id: nextMessageId++, role: "user", content: message },
    ]);
    chatMutation.mutate(message);
    setInput("");
  };

  const chatMutation = useMutation({
    mutationFn: (message: string) => stockApi.chat(message, symbol, provider || undefined),
    onSuccess: (res) => {
      // The backend already extracts the final answer and strips the inline
      // [Source: …] tags into structured citations — no client-side scrubbing.
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId++,
          role: "assistant",
          content: res.data.answer || "The model returned an empty answer.",
          citations: res.data.citations || [],
          provider: res.data.provider,
          model: res.data.model,
        },
      ]);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId++,
          role: "assistant",
          content: "Sorry, I couldn't process that question. Please try again.",
          failed: true,
        },
      ]);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || chatMutation.isPending) return;
    send(text);
  };

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col h-[500px] max-h-[70vh]">
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
            {msg.role === "assistant" ? (
              <>
                {/* Answer bubble */}
                <div className="max-w-[90%] rounded-xl px-4 py-3 text-sm leading-relaxed bg-muted text-foreground border border-border/50">
                  {msg.model && (
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70 font-medium mb-1.5">
                      via {msg.model}
                    </div>
                  )}
                  {msg.content}
                </div>

                {/* Sources footer */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-2 w-full max-w-[90%]">
                    <p className="text-xs text-muted-foreground mb-1 font-medium">Sources</p>
                    <div className="flex flex-wrap gap-2">
                      {msg.citations.map((cit, j) => {
                        const inner = cit.text ? (
                          <>
                            <span className="text-primary">•</span>
                            <span>{cit.text}</span>
                          </>
                        ) : null;
                        // Only http(s) links become anchors; anything else (a
                        // `javascript:` URL from prompt-injected content, or a
                        // relative path) renders as plain text.
                        const href = safeExternalUrl(cit.url);
                        return href ? (
                          <a
                            key={j}
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1.5 text-xs text-primary bg-muted/30 rounded px-2 py-1 hover:bg-muted/60 underline underline-offset-2"
                          >
                            {inner}
                          </a>
                        ) : (
                          <div
                            key={j}
                            className="flex items-center gap-1.5 text-xs text-muted-foreground bg-muted/30 rounded px-2 py-1"
                          >
                            {inner}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {msg.failed && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2 gap-1.5 text-xs"
                    onClick={() => {
                      const lastUser = [...messages].reverse().find((m) => m.role === "user");
                      if (lastUser && !chatMutation.isPending) chatMutation.mutate(lastUser.content);
                    }}
                  >
                    <RotateCcw className="w-3 h-3" /> Retry
                  </Button>
                )}
              </>
            ) : (
              /* User bubble */
              <div className="max-w-[80%] rounded-xl px-4 py-3 text-sm bg-primary text-primary-foreground">
                {msg.content}
              </div>
            )}
          </div>
        ))}

        {chatMutation.isPending && (
          <div className="flex items-start">
            <div className="bg-muted rounded-xl px-4 py-3 text-sm max-w-[80%]">
              <Skeleton className="h-4 w-48" />
            </div>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ${symbol}... e.g. "Should I buy ${symbol} at current prices?"`}
          className="flex-1 rounded-xl border border-input bg-background px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          disabled={chatMutation.isPending}
          aria-label="Message the AI advisor"
        />
        {providerOptions.length > 1 && (
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={chatMutation.isPending}
            className="rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            aria-label="LLM provider"
          >
            {providerOptions.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        )}
        <Button type="submit" disabled={chatMutation.isPending || !input.trim()} size="icon" aria-label="Send message">
          <Send className="w-4 h-4" />
        </Button>
      </form>

      <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
        <AlertTriangle className="w-3 h-3" />
        AI responses are not financial advice. Always verify with official sources.
      </div>
    </div>
  );
}
