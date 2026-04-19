"use client";

import {
  Download,
  ExternalLink,
  ShieldCheck,
  Bot,
  FileCheck,
  AlertTriangle,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import { scoreColor } from "@/lib/utils";
import type { AnalysisResult } from "@/lib/types";

interface ResultsProps {
  result: AnalysisResult;
}

export default function Results({ result }: ResultsProps) {
  const toast = useToastStore();

  const downloadPdf = async () => {
    try {
      const res = await api.get(
        `/api/v1/export-pdf/${result.document_id}`,
        { responseType: "blob" }
      );
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `plagiarism-report-${result.document_id}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.add("success", "Report downloaded!");
    } catch {
      toast.add("error", "Failed to download report.");
    }
  };

  const originalScore = Math.max(0, 100 - (result.plagiarism_score ?? 0));

  return (
    <div className="space-y-6">
      {/* Score cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <ScoreCard
          label="Plagiarism"
          score={result.plagiarism_score}
          icon={<ShieldCheck className="w-5 h-5" />}
        />
        <ScoreCard
          label="Original"
          score={originalScore}
          icon={<FileCheck className="w-5 h-5" />}
        />
        {result.ai_score !== undefined && (
          <ScoreCard
            label="AI Detection"
            score={result.ai_score}
            icon={<Bot className="w-5 h-5" />}
          />
        )}
        <div className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center justify-center">
          <AlertTriangle className="w-5 h-5 text-muted mb-1" />
          <span className="text-xs text-muted mb-1">Risk Level</span>
          <Badge
            variant={
              result.risk_level === "LOW"
                ? "success"
                : result.risk_level === "MEDIUM"
                ? "warning"
                : "danger"
            }
          >
            {result.risk_level}
          </Badge>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={downloadPdf}
          className="flex items-center gap-2 px-4 py-2 bg-surface2 hover:bg-border text-txt rounded-xl text-sm font-medium transition-colors border border-border"
        >
          <Download className="w-4 h-4" />
          Download PDF
        </button>
      </div>

      {/* Detected sources */}
      {result.detected_sources && result.detected_sources.length > 0 && (
        <Card>
          <h3 className="text-lg font-semibold mb-4">
            Detected Sources ({result.detected_sources.length})
          </h3>
          <div className="space-y-3">
            {result.detected_sources.map((source, i) => (
              <div
                key={i}
                className="flex items-start gap-3 p-3 bg-bg rounded-xl"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-sm font-semibold ${scoreColor(source.similarity * 100)}`}>
                      {(source.similarity * 100).toFixed(1)}%
                    </span>
                    <Badge variant="default">{source.source_type}</Badge>
                  </div>
                  <p className="text-sm font-medium truncate">
                    {source.title || source.url}
                  </p>
                  {source.url && (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-accent-l hover:text-accent flex items-center gap-1 mt-1"
                    >
                      <ExternalLink className="w-3 h-3" />
                      {source.url.length > 60
                        ? source.url.slice(0, 60) + "…"
                        : source.url}
                    </a>
                  )}
                </div>
                <span className="text-xs text-muted whitespace-nowrap">
                  {source.matched_words} words
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Flagged passages — side-by-side comparison */}
      {result.flagged_passages && result.flagged_passages.length > 0 && (
        <Card>
          <h3 className="text-lg font-semibold mb-4">
            Flagged Passages ({result.flagged_passages.length})
          </h3>
          <div className="space-y-3">
            {result.flagged_passages.map((passage, i) => {
              const isUrl =
                passage.source &&
                (passage.source.startsWith("http://") ||
                  passage.source.startsWith("https://"));
              const matchedSrc = result.detected_sources?.find(
                (s) => s.url && passage.source && s.url === passage.source,
              );
              const sourceTitle = matchedSrc?.title || passage.source || "Unknown";
              const sourceType = matchedSrc?.source_type || "Internet";
              return (
                <div
                  key={i}
                  className="border-l-4 border-danger/30 rounded-r-xl overflow-hidden bg-danger/5"
                >
                  {/* Header */}
                  <div className="flex items-center gap-2 px-4 pt-3 pb-1 flex-wrap">
                    <span
                      className={`text-xs font-semibold ${scoreColor(
                        passage.similarity_score * 100
                      )}`}
                    >
                      {(passage.similarity_score * 100).toFixed(1)}% similar
                    </span>
                    <span className="px-1.5 py-0.5 text-[10px] font-medium bg-surface2 border border-border rounded text-muted">
                      {sourceType}
                    </span>
                    {matchedSrc && (
                      <span className="text-xs text-muted">
                        {matchedSrc.matched_words ?? 0} words matched
                      </span>
                    )}
                  </div>
                  {/* Side-by-side */}
                  <div className="grid grid-cols-1 md:grid-cols-2">
                    {/* Left: Your document text */}
                    <div className="px-4 py-3 md:border-r md:border-border/30">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <div className="w-2 h-2 rounded-full bg-danger/60" />
                        <span className="text-[10px] font-semibold text-danger uppercase tracking-wide">Your Document</span>
                      </div>
                      <p className="text-sm text-txt/80 leading-relaxed">
                        {passage.text}
                      </p>
                    </div>
                    {/* Right: Source info */}
                    <div className="px-4 py-3 bg-surface2/30">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <div className="w-2 h-2 rounded-full bg-accent/60" />
                        <span className="text-[10px] font-semibold text-accent uppercase tracking-wide">Matched Source</span>
                      </div>
                      <p className="text-sm font-medium text-txt mb-1">{sourceTitle}</p>
                      {isUrl && (
                        <a
                          href={passage.source}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-accent-l hover:text-accent break-all leading-relaxed"
                        >
                          {passage.source!.length > 80 ? passage.source!.slice(0, 80) + "\u2026" : passage.source}
                        </a>
                      )}
                      <div className="mt-2 pt-2 border-t border-border/30">
                        <p className="text-xs text-muted italic mb-2">
                          This passage closely matches content from the above source.
                        </p>
                        {isUrl && (
                          <a
                            href={passage.source}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-accent-l hover:text-accent bg-accent/10 hover:bg-accent/15 rounded-lg transition-colors"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                            View full source
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

function ScoreCard({
  label,
  score,
  icon,
}: {
  label: string;
  score: number;
  icon: React.ReactNode;
}) {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center">
      <div className={`mb-1 ${scoreColor(label === "Original" ? 100 - score : score)}`}>
        {icon}
      </div>
      <span className="text-xs text-muted mb-1">{label}</span>
      <span
        className={`text-2xl font-bold ${scoreColor(
          label === "Original" ? 100 - score : score
        )}`}
      >
        {(score ?? 0).toFixed(1)}%
      </span>
    </div>
  );
}
