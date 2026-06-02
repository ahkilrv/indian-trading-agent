"use client";

import { useState, useRef, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, MessageSquare, X, Send, Bot, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { sendChatMessage } from "@/lib/api";
import { TradingViewLink } from "@/components/TradingViewLink";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatBotProps {
  ticker: string;
  tradeDate: string;
  signal: string;
  reports: Record<string, string>;
  debates: { bull: string; bear: string };
  riskDebates: { aggressive: string; conservative: string; neutral: string };
  stats?: {
    llm_calls?: number;
    tool_calls?: number;
    tokens_in?: number;
    tokens_out?: number;
    total_tokens?: number;
    cost_usd?: number;
    cost_inr?: number;
    per_model?: Record<string, { input: number; output: number }>;
  } | null;
  duration: number | null;
}

export function ChatBot({
  ticker,
  tradeDate,
  signal,
  reports,
  debates,
  riskDebates,
  stats,
  duration,
}: ChatBotProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when chat opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMsg: ChatMessage = { role: "user", content: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      // Build history from existing messages (excluding the one we just added)
      const history = messages.map((m) => ({ role: m.role, content: m.content }));

      const result = await sendChatMessage({
        message: trimmed,
        ticker,
        trade_date: tradeDate,
        signal,
        reports,
        debates,
        risk_debates: riskDebates,
        stats: stats ?? undefined,
        history,
        duration,
      });

      const assistantMsg: ChatMessage = { role: "assistant", content: result.reply };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      setError(e.message || "Failed to get response");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Collapsed toggle button
  if (!open) {
    return (
      <div className="fixed bottom-6 right-6 z-50">
        <Button
          onClick={() => setOpen(true)}
          className="shadow-lg rounded-full px-5 py-6"
          size="lg"
        >
          <MessageSquare className="h-5 w-5 mr-2" />
          Ask AI about this analysis
        </Button>
      </div>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[420px] max-w-[90vw]">
      <Card className="shadow-2xl border border-border overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-primary/10 border-b border-border">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            <span className="font-semibold text-sm">
              Analysis Chat — {ticker}
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setOpen(false)}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Messages */}
        <CardContent className="p-0">
          <div className="h-[360px] overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="text-center text-muted-foreground py-8">
                <Bot className="h-8 w-8 mx-auto mb-2 opacity-40" />
                <p className="text-sm">
                  Ask me anything about this analysis — the signal, reports,
                  debates, or reasoning behind the verdict.
                </p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-2 ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {msg.role === "assistant" && (
                  <div className="flex-shrink-0 mt-1">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                )}
                <div
                  className={`rounded-lg px-3 py-2 text-sm max-w-[85%] ${
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted"
                  }`}
                >
                  {msg.role === "assistant" ? (
                    <div className="prose prose-sm dark:prose-invert max-w-none break-words [&_pre]:whitespace-pre-wrap [&_code]:break-all">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                  )}
                </div>
                {msg.role === "user" && (
                  <div className="flex-shrink-0 mt-1">
                    <User className="h-4 w-4 text-muted-foreground" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-2 justify-start">
                <div className="flex-shrink-0 mt-1">
                  <Bot className="h-4 w-4 text-primary" />
                </div>
                <div className="bg-muted rounded-lg px-3 py-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}

            {error && (
              <div className="text-center text-red-500 text-sm py-2">{error}</div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </CardContent>

        {/* Input */}
        <div className="flex gap-2 p-3 border-t border-border bg-background">
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this analysis..."
            disabled={loading}
            className="h-9 text-sm"
          />
          <Button
            size="icon"
            className="h-9 w-9 flex-shrink-0"
            onClick={handleSend}
            disabled={loading || !input.trim()}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </Card>
    </div>
  );
}