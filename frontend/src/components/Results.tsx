"use client";

import { useMemo, useState } from "react";
import {
  Download,
  ExternalLink,
  ShieldCheck,
  Bot,
  AlertTriangle,
  Info,
  X,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import { scoreColor, RISK_TOOLTIP } from "@/lib/utils";
import type { AnalysisResult } from "@/lib/types";
import {
  PassageCard,
  PassagesEmptyState,
  AdjustedScorePill,
  useSourcesByUrl,
} from "@/components/passage-shared";
import {
  useDismissalsStore,
  adjustedScore,
} from "@/lib/stores/dismissals-store";

interface ResultsProps {
  result: AnalysisResult;
}

export default function Results({ result }: ResultsProps) {
  const toast = useToastStore();
  const [selectedSource, setSelectedSource] = useState<string | null>(null);

  const dismissedForDoc = useDismissalsStore(
    (s) => s.dismissed[result.document_id],
  );
  const clearAll = useDismissalsStore((s) => s.clearAll);

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

  const allPassages = useMemo(
    () => result.flagged_passages ?? [],
    [result.flagged_passages],
  );
  const sourcesByUrl = useSourcesByUrl(result.detected_sources);

  // Filter visible passages by selected source. Passages with no URL are
  // collected separately so they aren't silently hidden when a filter is on.
  const { visiblePassages, unlinkedCount } = useMemo(() => {
    const isUrl = (s: string | undefined | null) =>
      !!s && (s.startsWith("http://") || s.startsWith("https://"));
    const unlinked = allPassages.filter((p) => !isUrl(p.source));
    if (!selectedSource) return { visiblePassages: allPassages, unlinkedCount: 0 };
    return {
      visiblePassages: allPassages.filter((p) => p.source === selectedSource),
      unlinkedCount: unlinked.length,
    };
  }, [allPassages, selectedSource]);

  const dismissedCount = dismissedForDoc
    ? Object.keys(dismissedForDoc).length
    : 0;
  const adjusted = useMemo(
    () =>
      adjustedScore(
        result.plagiarism_score ?? 0,
        allPassages,
        dismissedForDoc,
      ),
    [result.plagiarism_score, allPassages, dismissedForDoc],
  );

  return (
    <div className="space-y-6">
      {/* Score cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <ScoreCard
          label="Matched against external sources"
          score={result.plagiarism_score}
          icon={<ShieldCheck className="w-5 h-5" />}
          tooltip="Percentage of your document that overlaps with possible sources. Includes quotes and citations unless dismissed."
          colorize
        />
        {result.ai_score !== undefined && (
          <ScoreCard
            label="AI-likeness signal (unreliable)"
            score={result.ai_score}
            icon={<Bot className="w-5 h-5" />}
            tooltip="AI detectors are unreliable. Treat as a hint, never as proof. We deliberately render this in a neutral color so the visual doesn't override the disclaimer."
            colorize={false}
          />
        )}
        <div
          className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center justify-center"
          title={RISK_TOOLTIP}
        >
          <AlertTriangle className="w-5 h-5 text-muted mb-1" />
          <span className="text-xs text-muted mb-1 flex items-center gap-1">
            Risk Level
            <Info className="w-3 h-3 text-muted/60" />
          </span>
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
          <details className="mt-2 text-[10px] text-muted/80 max-w-[18ch]">
            <summary className="cursor-pointer hover:text-txt">
              Thresholds
            </summary>
            <p className="mt-1 leading-snug">{RISK_TOOLTIP}</p>
          </details>
        </div>
      </div>

      {/* Adjusted-score pill + actions */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={downloadPdf}
          className="flex items-center gap-2 px-4 py-2 bg-surface2 hover:bg-border text-txt rounded-xl text-sm font-medium transition-colors border border-border"
        >
          <Download className="w-4 h-4" />
          Download PDF
        </button>
        <AdjustedScorePill
          original={result.plagiarism_score ?? 0}
          adjusted={adjusted}
          dismissedCount={dismissedCount}
          onReset={() => clearAll(result.document_id)}
        />
      </div>

      {/* Possible matching sources */}
      {result.detected_sources && result.detected_sources.length > 0 && (
        <Card>
          <div className="flex items-baseline justify-between mb-1 flex-wrap gap-2">
            <h3 className="text-lg font-semibold">
              Possible Matching Sources ({result.detected_sources.length})
            </h3>
            {selectedSource && (
              <button
                onClick={() => setSelectedSource(null)}
                className="text-xs text-accent-l hover:text-accent flex items-center gap-1"
              >
                <X className="w-3 h-3" />
                Clear filter
              </button>
            )}
          </div>
          <p className="text-xs text-muted mb-4">
            Candidates ranked by similarity. Click a source to filter passages.
            These are possible sources, not confirmed origins.
          </p>
          <div className="space-y-3">
            {result.detected_sources.map((source, i) => {
              const pct = source.similarity * 100;
              const isSelected = selectedSource === source.url;
              return (
                <button
                  key={i}
                  onClick={() =>
                    setSelectedSource(isSelected ? null : source.url)
                  }
                  className={`w-full text-left flex items-start gap-3 p-3 rounded-xl transition-colors border ${
                    isSelected
                      ? "bg-accent/10 border-accent/40"
                      : "bg-bg border-transparent hover:bg-surface2"
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-sm font-semibold ${scoreColor(pct)}`}>
                        {pct.toFixed(0)}%
                      </span>
                      <Badge variant="default">{source.source_type}</Badge>
                      {isSelected && (
                        <span className="text-[10px] text-accent-l uppercase tracking-wide">
                          Filtering
                        </span>
                      )}
                    </div>
                    <p className="text-sm font-medium truncate">
                      {source.title || source.url}
                    </p>
                    {source.url && (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={source.url}
                        onClick={(e) => e.stopPropagation()}
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
                </button>
              );
            })}
          </div>
        </Card>
      )}

      {/* Flagged passages */}
      {visiblePassages.length > 0 ? (
        <Card>
          <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
            <h3 className="text-lg font-semibold">
              Flagged Passages ({visiblePassages.length}
              {selectedSource && ` of ${allPassages.length}`})
            </h3>
            {selectedSource && (
              <button
                onClick={() => setSelectedSource(null)}
                className="text-xs text-accent-l hover:text-accent flex items-center gap-1"
              >
                <X className="w-3 h-3" />
                Show all passages
              </button>
            )}
          </div>
          {selectedSource && unlinkedCount > 0 && (
            <p className="text-xs text-muted mb-3">
              {unlinkedCount} passage{unlinkedCount === 1 ? "" : "s"} with no
              source link {unlinkedCount === 1 ? "is" : "are"} hidden by this
              filter.
            </p>
          )}
          <div className="space-y-3">
            {visiblePassages.map((passage) => {
              const matchedSrc =
                (passage.source && sourcesByUrl.get(passage.source)) ||
                undefined;
              // Stable index across the full passage list — needed so
              // dismissal state survives filter changes.
              const passageIndex = allPassages.indexOf(passage);
              return (
                <PassageCard
                  key={passageIndex}
                  documentId={result.document_id}
                  passage={passage}
                  passageIndex={passageIndex}
                  matchedSource={matchedSrc}
                />
              );
            })}
          </div>
        </Card>
      ) : (
        <PassagesEmptyState
          allPassagesEmpty={allPassages.length === 0}
          selectedSource={selectedSource}
          onClearFilter={() => setSelectedSource(null)}
          emptyReason={result.empty_reason ?? null}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ScoreCard
// ---------------------------------------------------------------------------

function ScoreCard({
  label,
  score,
  icon,
  tooltip,
  colorize,
}: {
  label: string;
  score: number;
  icon: React.ReactNode;
  tooltip?: string;
  /**
   * When false, render in muted/neutral colors regardless of value.
   * Used for the AI-likeness tile so the color doesn't contradict the
   * "this metric is unreliable" disclaimer.
   */
  colorize: boolean;
}) {
  const value = score ?? 0;
  const colorClass = colorize ? scoreColor(value) : "text-muted";
  return (
    <div
      className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center"
      title={tooltip}
    >
      <div className={`mb-1 ${colorClass}`}>{icon}</div>
      <div className={`text-3xl font-bold ${colorClass}`}>
        {value.toFixed(0)}%
      </div>
      <div className="text-xs text-muted mt-1 text-center max-w-[16ch] flex items-center gap-1">
        {label}
        {tooltip && <Info className="w-3 h-3 text-muted/60 shrink-0" />}
      </div>
    </div>
  );
}
