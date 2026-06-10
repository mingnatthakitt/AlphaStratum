"use client";

import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Send, AlertTriangle } from "lucide-react";

interface MetricCard {
  label: string;
  value: string;
  source?: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: { text: string; source: string; url?: string }[];
  metrics?: MetricCard[];
  provider?: string;
  model?: string;
}

interface Props {
  symbol: string;
}

export default function ChatAdvisor({ symbol }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
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

  // Initialize selected provider to whatever the server defaults to
  useEffect(() => {
    if (providersData && !provider) {
      setProvider(providersData.default);
    }
  }, [providersData, provider]);

  const availableProviders = providersData?.available || {};
  const modelNames: { anthropic?: string; gemini?: string } = providersData?.models || {};
  const providerOptions = [
    { key: "anthropic", label: modelNames.anthropic || "Anthropic" },
    { key: "gemini", label: modelNames.gemini || "Gemini" },
  ].filter((p) => availableProviders[p.key as keyof typeof availableProviders]);

  const chatMutation = useMutation({
    mutationFn: (message: string) => stockApi.chat(message, symbol, provider || undefined),
    onSuccess: (res) => {
      const rawAnswer = res.data.answer || "";
      const citations = res.data.citations || [];

      // Strategy: find the actual answer — it's the first paragraph that doesn't start with *
      // and comes after a blank line or after * Sentence N: lines.
      // We split on double newlines to find paragraph blocks.
      const blocks = rawAnswer.split(/\n\n+/);

      let answerText = rawAnswer; // fallback to full response
      const metrics: MetricCard[] = [];

      // Find the first block that looks like a real answer (starts with a stock symbol or capital letter, no * prefix)
      for (const block of blocks) {
        const firstLine = block.trim().split("\n")[0].trim();
        // Skip blocks that are all *-prefixed lines (the prompt echo)
        const allStarred = block.trim().split("\n").every((l) => l.trim().startsWith("*"));
        if (!allStarred && !firstLine.startsWith("*")) {
          answerText = block.trim();
          break;
        }
      }

      // If answer is still the raw response, clean it by stripping all *-prefixed lines
      if (answerText === rawAnswer) {
        const cleaned = rawAnswer
          .split("\n")
          .filter((l) => {
            const t = l.trim();
            // Remove echoed prompt lines
            if (/^\* Role:/i.test(t)) return false;
            if (/^\* Critical Rules/i.test(t)) return false;
            if (/^\* User Question/i.test(t)) return false;
            if (/^\* Ticker:/i.test(t)) return false;
            if (/^\* Performance:/i.test(t)) return false;
            if (/^\* China Market:/i.test(t)) return false;
            if (/^\* General Sentiment:/i.test(t)) return false;
            if (/^\* Sentence \d+:/i.test(t)) return false;
            // Keep numeric metric lines as cards
            const metricMatch = t.match(/^\* (.+?): (.+?)(\s*\[Source: [^\]]+\])?$/);
            if (metricMatch && /[\$\%\d]/.test(metricMatch[2])) {
              const label = metricMatch[1].trim();
              const value = metricMatch[2].trim().replace(/\s*\[Source: [^\]]+\]/, "").trim();
              const src = t.match(/\[Source: ([^\]]+)\]/)?.[1];
              metrics.push({ label, value, source: src });
              return false;
            }
            // Skip any remaining *-prefixed lines
            if (t.startsWith("*")) return false;
            return true;
          })
          .join("\n")
          .trim();
        if (cleaned) answerText = cleaned;
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: answerText,
          citations,
          metrics: metrics.length > 0 ? metrics : undefined,
          provider: res.data.provider,
          model: res.data.model,
        },
      ]);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, I couldn't process that question. Please try again.",
 },
      ]);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || chatMutation.isPending) return;

    setMessages((prev) => [...prev, { role: "user", content: input.trim() }]);
    chatMutation.mutate(input.trim());
    setInput("");
  };

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col h-[500px]">
      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
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

                {/* Structured metric cards (if any) */}
                {msg.metrics && msg.metrics.length > 0 && (
                  <div className="mt-2 w-full max-w-[90%]">
                    <div className="grid grid-cols-3 gap-2">
                      {msg.metrics.map((m, j) => (
                        <div key={j} className="bg-muted/50 rounded-lg px-3 py-2 border border-border/40">
                          <p className="text-xs text-muted-foreground">{m.label}</p>
                          <p className="text-sm font-bold mt-0.5">{m.value}</p>
                          {m.source && (
                            <p className="text-xs text-muted-foreground/60 mt-0.5">{m.source}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Sources footer */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-2 w-full max-w-[90%]">
                    <p className="text-xs text-muted-foreground mb-1 font-medium">Sources</p>
                    <div className="flex flex-wrap gap-2">
                      {msg.citations.map((cit, j) => (
                        <div key={j} className="flex items-center gap-1.5 text-xs text-muted-foreground bg-muted/30 rounded px-2 py-1">
                          <span className="text-primary">•</span>
                          <span>{cit.text}</span>
                        </div>
                      ))}
                    </div>
                  </div>
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
        />
        {providerOptions.length > 1 && (
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={chatMutation.isPending}
            className="rounded-xl border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            title="LLM provider"
          >
            {providerOptions.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
        )}
        <Button type="submit" disabled={chatMutation.isPending || !input.trim()} size="icon">
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
