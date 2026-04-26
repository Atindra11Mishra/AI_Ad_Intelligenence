"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import { ChatMessage } from "@/lib/types";
import { useBrand } from "@/components/BrandProvider";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function ChatPage() {
  const { selectedBrandId, selectedBrand } = useBrand();

  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom whenever history updates
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!selectedBrandId || !message.trim() || streaming) return;

    const userMessage: ChatMessage = {
      role: "user",
      content: message.trim(),
    };

    const nextHistory = [...history, userMessage];

    setHistory([...nextHistory, { role: "assistant", content: "" }]);
    setMessage("");
    setStreaming(true);
    setError("");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        signal: controller.signal,
        body: JSON.stringify({
          brand_id: selectedBrandId,
          message: userMessage.content,
          history,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(await res.text());
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      let assistantText = "";

      while (true) {
        const { done, value } = await reader.read();

        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        assistantText += chunk;

        setHistory([...nextHistory, { role: "assistant", content: assistantText }]);
      }
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err.message || "Chat request failed");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
    setStreaming(false);
  }

  if (!selectedBrandId) {
    return (
      <Card>
        <CardContent className="py-10">
          <p className="text-muted-foreground">
            Select or create a brand before using creative intelligence chat.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Creative Intelligence Chat
        </h1>
        <p className="text-muted-foreground">
          Selected brand: {selectedBrand?.name}
        </p>
      </div>

      <Card className="min-h-[560px]">
        <CardHeader>
          <CardTitle>Ask about the competitive landscape</CardTitle>
        </CardHeader>

        <CardContent className="flex h-[620px] flex-col gap-4">
          <ScrollArea className="h-[440px] rounded-lg border p-4">
            <div className="space-y-4">
              {history.length === 0 && (
                <div className="space-y-2 text-sm text-muted-foreground">
                  <p>Try asking:</p>
                  <p>&quot;What creative angles would work best for my brand?&quot;</p>
                  <p>&quot;What hooks are my competitors overusing?&quot;</p>
                  <p>&quot;Give me 3 ad concepts none of my competitors are running.&quot;</p>
                </div>
              )}

              {history.map((item, index) => (
                <div
                  key={index}
                  className={
                    item.role === "user"
                      ? "ml-auto max-w-[80%] rounded-xl bg-primary px-4 py-3 text-primary-foreground"
                      : "mr-auto max-w-[85%] rounded-xl border bg-muted px-4 py-3"
                  }
                >
                  <p className="mb-1 text-xs font-medium uppercase opacity-70">
                    {item.role}
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">
                    {item.content}
                  </p>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>

          {error && <p className="text-sm text-red-500">{error}</p>}

          <form onSubmit={handleSubmit} className="space-y-3">
            <Textarea
              placeholder="Ask for hooks, angles, visual trends, carousel concepts..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
            />

            <div className="flex justify-end gap-3">
              {streaming && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={stopStreaming}
                >
                  Stop
                </Button>
              )}

              <Button type="submit" disabled={streaming || !message.trim()}>
                {streaming ? "Streaming..." : "Send"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
