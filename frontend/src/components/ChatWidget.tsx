"use client";

import { useState, useRef, useEffect } from "react";
import { MessageCircle, X, Send } from "lucide-react";
import api from "@/lib/api";
import { Spinner } from "@/components/ui";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hi! How can I help you with PlagiarismGuard?" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    const userMsg: Message = { role: "user", content: text };
    setMessages((m) => [...m, userMsg]);
    setLoading(true);
    try {
      const res = await api.post("/api/v1/chatbot/message", {
        message: text,
        history: messages.slice(-10),
      });
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.data.reply || res.data.message || "Sorry, I couldn't understand that." },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Something went wrong. Please try again." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-accent hover:bg-accent/90 text-white rounded-full shadow-lg shadow-accent/30 flex items-center justify-center transition-transform hover:scale-105"
      >
        {open ? <X className="w-6 h-6" /> : <MessageCircle className="w-6 h-6" />}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-80 sm:w-96 bg-surface border border-border rounded-2xl shadow-2xl flex flex-col max-h-[500px]">
          <div className="px-4 py-3 border-b border-border flex items-center gap-2">
            <MessageCircle className="w-4 h-4 text-accent" />
            <span className="text-sm font-semibold">Chat Support</span>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-[200px]">
            {messages.map((m, i) => (
              <div
                key={i}
                className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] px-3 py-2 rounded-xl text-sm ${
                    m.role === "user"
                      ? "bg-accent text-white"
                      : "bg-bg text-txt/80"
                  }`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="px-3 py-2 bg-bg rounded-xl">
                  <Spinner size="sm" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="p-3 border-t border-border">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Type a message…"
                className="flex-1 bg-bg border border-border rounded-xl px-3 py-2 text-sm text-txt placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/50"
              />
              <button
                onClick={send}
                disabled={loading || !input.trim()}
                className="p-2 bg-accent hover:bg-accent/90 text-white rounded-xl transition-colors disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
