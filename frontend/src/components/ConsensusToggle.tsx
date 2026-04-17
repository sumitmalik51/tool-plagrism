"use client";

import { useState } from "react";
import { AlertTriangle, Check, X } from "lucide-react";

export default function ConsensusToggle() {
  const [mode, setMode] = useState<"without" | "with">("with");

  return (
    <div>
      {/* Toggle */}
      <div className="flex justify-center mb-8">
        <div className="inline-flex bg-surface border border-border/60 rounded-full p-1">
          <button
            onClick={() => setMode("without")}
            className={`px-5 py-2 text-xs font-medium rounded-full transition-colors ${
              mode === "without" ? "bg-danger/15 text-danger" : "text-muted hover:text-txt"
            }`}
          >
            Without PlagiarismGuard
          </button>
          <button
            onClick={() => setMode("with")}
            className={`px-5 py-2 text-xs font-medium rounded-full transition-colors ${
              mode === "with" ? "bg-ok/15 text-ok" : "text-muted hover:text-txt"
            }`}
          >
            With PlagiarismGuard
          </button>
        </div>
      </div>

      {/* Result panel */}
      <div className="bg-surface border border-border/60 rounded-2xl p-6 sm:p-8">
        <div className="flex items-center justify-between mb-5 pb-5 border-b border-border/60">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-1">
              Same input text
            </p>
            <p className="text-sm text-txt/90">
              &ldquo;Machine learning models have revolutionized natural language processing. Transformer
              architectures demonstrate remarkable capabilities in text generation...&rdquo;
            </p>
          </div>
        </div>

        {mode === "without" ? (
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-danger">
                Output — single-model tool
              </p>
            </div>

            <div className="bg-bg border border-border/60 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm text-muted">Plagiarism Score</span>
                <span className="text-3xl font-bold text-txt">8%</span>
              </div>
              <div className="h-1.5 bg-surface2 rounded-full overflow-hidden">
                <div className="h-full bg-ok w-[8%]" />
              </div>
              <p className="text-xs text-muted mt-3">Status: Original content — passes check</p>
            </div>

            <div className="space-y-2 text-sm">
              {[
                { text: "AI-generated paragraph — undetected", icon: <X className="w-3.5 h-3.5" /> },
                { text: "arXiv paper on transformers — not checked", icon: <X className="w-3.5 h-3.5" /> },
                { text: "Paraphrased section from Vaswani et al. — missed", icon: <X className="w-3.5 h-3.5" /> },
                { text: "No risk level. No sources listed. No audit trail.", icon: <X className="w-3.5 h-3.5" /> },
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2 text-muted">
                  <span className="text-danger shrink-0 mt-0.5">{item.icon}</span>
                  {item.text}
                </div>
              ))}
            </div>

            <div className="flex items-start gap-2 bg-danger/5 border border-danger/20 rounded-lg px-4 py-3 text-xs">
              <AlertTriangle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
              <span className="text-txt/80">
                Output reaches student, editor, or reviewer with <strong>false confidence</strong> — three distinct originality risks went undetected.
              </span>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ok">
                Output — 5-agent consensus
              </p>
            </div>

            {/* Multi-dimensional score */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-bg border border-border/60 rounded-xl p-4">
                <p className="text-[10px] uppercase tracking-wider text-muted mb-1">Plagiarism</p>
                <p className="text-2xl font-bold text-danger">34%</p>
              </div>
              <div className="bg-bg border border-border/60 rounded-xl p-4">
                <p className="text-[10px] uppercase tracking-wider text-muted mb-1">AI Content</p>
                <p className="text-2xl font-bold text-accent-l">62%</p>
              </div>
              <div className="bg-bg border border-border/60 rounded-xl p-4">
                <p className="text-[10px] uppercase tracking-wider text-muted mb-1">Risk Level</p>
                <p className="text-2xl font-bold text-warn">High</p>
              </div>
            </div>

            <div className="space-y-2 text-sm">
              {[
                { text: "Academic Agent: matched arXiv:1706.03762 (Vaswani et al., 2017) — 87% similarity", icon: <Check className="w-3.5 h-3.5" /> },
                { text: "AI Detection Agent: GPT-4 signature detected in paragraph 2 (confidence 94%)", icon: <Check className="w-3.5 h-3.5" /> },
                { text: "Semantic Agent: paraphrased content mapped to 2 source papers", icon: <Check className="w-3.5 h-3.5" /> },
                { text: "Report Agent: full audit trail with source URLs + confidence intervals", icon: <Check className="w-3.5 h-3.5" /> },
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2 text-muted">
                  <span className="text-ok shrink-0 mt-0.5">{item.icon}</span>
                  {item.text}
                </div>
              ))}
            </div>

            <div className="flex items-start gap-2 bg-ok/5 border border-ok/20 rounded-lg px-4 py-3 text-xs">
              <Check className="w-4 h-4 text-ok shrink-0 mt-0.5" />
              <span className="text-txt/80">
                Reviewer sees the <strong>full picture</strong> — three distinct risks flagged with sources, confidence scores, and an exportable audit trail.
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
