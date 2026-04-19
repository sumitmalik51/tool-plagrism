"use client";

import { useMemo, useState } from "react";
import {
  Download,
  ExternalLink,
  ShieldCheck,
  Bot,
  AlertTriangle,
  Info,
  Equal,
  Sparkles,
  Search,
  X,
  FileX,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import { scoreColor, passageBand, passageExplanation } from "@/lib/utils";
import type { AnalysisResult, FlaggedPassage } from "@/lib/types";

interface ResultsProps {
  result: AnalysisResult;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type MatchType = NonNullable<FlaggedPassage["match_type"]>;

interface MatchChipMeta {
  symbol: React.ReactNode;
  label: string;
  tooltip: string;
  className: string;
}

function matchTypeMeta(t: MatchType | null | undefined): MatchChipMeta | null {
  switch (t) {
    case "exact":
      return {
        symbol: <Equal className="w-3 h-3" />,
        label: "Exact",
        tooltip: "Verbatim or near-verbatim overlap (long shared word run).",
        className: "bg-rose-500/10 text-rose-300 border-rose-500/30",
      };
    case "paraphrase":
      return {
        symbol: <span className="text-[11px] leading-none font-bold">≈</span>,
        label: "Paraphrase",
        tooltip:
          "Reworded text that still shares rare phrases with a candidate source.",
        className: "bg-amber-500/10 text-amber-300 border-amber-500/30",
      };
    case "semantic":
      return {
        symbol: <Sparkles className="w-3 h-3" />,
        label: "Semantic",
        tooltip:
          "Embedding-only similarity. No shared phrases — possibly the same idea, different words.",
        className: "bg-sky-500/10 text-sky-300 border-sky-500/30",
      };
    default:
      return null;
  }
}

// Tokenise into [word, separator] pairs so we can re-join preserving spacing.
function tokenize(text: string): string[] {
  return text.match(/\w+|\W+/g) ?? [];
}

// Build a set of shared 3-grams (lowercased word triples) between two texts.
function sharedTrigramSet(a: string, b: string): Set<string> {
  const wordsA = a.toLowerCase().match(/\w+/g) ?? [];
  const wordsB = b.toLowerCase().match(/\w+/g) ?? [];
  if (wordsA.length < 3 || wordsB.length < 3) return new Set();
  const trisB = new Set<string>();
  for (let i = 0; i <= wordsB.length - 3; i++) {
    trisB.add(`${wordsB[i]} ${wordsB[i + 1]} ${wordsB[i + 2]}`);
  }
  const shared = new Set<string>();
  for (let i = 0; i <= wordsA.length - 3; i++) {
    const tri = `${wordsA[i]} ${wordsA[i + 1]} ${wordsA[i + 2]}`;
    if (trisB.has(tri)) shared.add(tri);
  }
  return shared;
}

// Render `text` with words highlighted when they belong to any shared trigram.
function HighlightedText({
  text,
  shared,
  highlightClass = "bg-amber-400/20 text-amber-100 rounded px-0.5",
}: {
  text: string;
  shared: Set<string>;
  highlightClass?: string;
}) {
  if (shared.size === 0 || !text) {
    return <>{text}</>;
  }
  const tokens = tokenize(text);
  const wordIndices: number[] = [];
  tokens.forEach((tok, i) => {
    if (/\w/.test(tok)) wordIndices.push(i);
  });
  const words = wordIndices.map((i) => tokens[i].toLowerCase());
  const highlightWord = new Array(wordIndices.length).fill(false);
  for (let i = 0; i <= words.length - 3; i++) {
    const tri = `${words[i]} ${words[i + 1]} ${words[i + 2]}`;
    if (shared.has(tri)) {
      highlightWord[i] = true;
      highlightWord[i + 1] = true;
      highlightWord[i + 2] = true;
    }
  }
  const tokenHighlighted = new Array(tokens.length).fill(false);
  wordIndices.forEach((tokIdx, wIdx) => {
    if (highlightWord[wIdx]) tokenHighlighted[tokIdx] = true;
  });
  // Coalesce adjacent highlighted runs (bridging single separator tokens
  // between two highlighted words) so spans look like phrases, not islands.
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < tokens.length) {
    if (tokenHighlighted[i]) {
      let j = i;
      while (j < tokens.length) {
        if (tokenHighlighted[j]) {
          j++;
          continue;
        }
        if (
          !/\w/.test(tokens[j]) &&
          j + 1 < tokens.length &&
          tokenHighlighted[j + 1]
        ) {
          j++;
          continue;
        }
        break;
      }
      out.push(
        <mark key={i} className={highlightClass}>
          {tokens.slice(i, j).join("")}
        </mark>,
      );
      i = j;
    } else {
      out.push(tokens[i]);
      i++;
    }
  }
  return <>{out}</>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Results({ result }: ResultsProps) {
  const toast = useToastStore();
  const [selectedSource, setSelectedSource] = useState<string | null>(null);

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

  const allPassages = result.flagged_passages ?? [];
  const visiblePassages = useMemo(
    () =>
      selectedSource
        ? allPassages.filter((p) => p.source === selectedSource)
        : allPassages,
    [allPassages, selectedSource],
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
        />
        {result.ai_score !== undefined && (
          <ScoreCard
            label="AI-likeness signal"
            score={result.ai_score}
            icon={<Bot className="w-5 h-5" />}
            tooltip="AI detectors are unreliable. Treat as a hint, never as proof."
          />
        )}
        <div
          className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center justify-center"
          title="Heuristic based on number and strength of matches. This is a flag for human review, not a verdict."
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
                          ? source.url.slice(0, 60) + "\u2026"
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

      {/* Flagged passages — side-by-side comparison */}
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
          <div className="space-y-3">
            {visiblePassages.map((passage, i) => {
              const pct = passage.similarity_score * 100;
              const band = passageBand(pct);
              const isUrl =
                passage.source &&
                (passage.source.startsWith("http://") ||
                  passage.source.startsWith("https://"));
              const matchedSrc = result.detected_sources?.find(
                (s) => s.url && passage.source && s.url === passage.source,
              );
              const sourceTitle = matchedSrc?.title || passage.source || "Unknown";
              const sourceType =
                matchedSrc?.source_type ||
                (isUrl ? "Internet" : "Unknown source");
              const explanation = passageExplanation(passage.reason, pct);
              const sourceSnippet = matchedSrc?.matched_passages?.[0]?.text;
              const chip = matchTypeMeta(passage.match_type);
              const shared = sourceSnippet
                ? sharedTrigramSet(passage.text, sourceSnippet)
                : new Set<string>();
              return (
                <div
                  key={i}
                  className={`border-l-4 ${band.borderClass} ${band.bgClass} rounded-r-xl overflow-hidden`}
                >
                  {/* Header */}
                  <div className="flex items-center gap-2 px-4 pt-3 pb-1 flex-wrap">
                    <span
                      aria-hidden="true"
                      className={`text-[10px] font-bold tracking-widest ${band.textClass}`}
                    >
                      {band.dots}
                    </span>
                    <span className={`text-xs font-semibold ${band.textClass}`}>
                      {band.label} · {pct.toFixed(0)}%
                    </span>
                    <span className="px-1.5 py-0.5 text-[10px] font-medium bg-surface2 border border-border rounded text-muted">
                      {sourceType}
                    </span>
                    {chip && (
                      <span
                        title={chip.tooltip}
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border rounded ${chip.className}`}
                      >
                        {chip.symbol}
                        {chip.label}
                      </span>
                    )}
                  </div>
                  {/* Side-by-side */}
                  <div className="grid grid-cols-1 md:grid-cols-2">
                    {/* Left: Your document text */}
                    <div className="px-4 py-3 md:border-r md:border-border/30">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <div className={`w-2 h-2 rounded-full ${band.bgClass.replace("/5", "/60").replace("/10", "/60")}`} />
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">
                          Your document
                        </span>
                      </div>
                      <p className="text-sm text-txt/80 leading-relaxed">
                        <HighlightedText text={passage.text} shared={shared} />
                      </p>
                    </div>
                    {/* Right: Source info + matched snippet */}
                    <div className="px-4 py-3 bg-surface2/30">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <div className="w-2 h-2 rounded-full bg-accent/60" />
                        <span className="text-[10px] font-semibold text-accent uppercase tracking-wide">
                          Matched source
                        </span>
                      </div>
                      <p className="text-sm font-medium text-txt mb-1">{sourceTitle}</p>
                      {isUrl && (
                        <a
                          href={passage.source}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={passage.source}
                          className="text-xs text-accent-l hover:text-accent break-all leading-relaxed"
                        >
                          {passage.source!.length > 80 ? passage.source!.slice(0, 80) + "\u2026" : passage.source}
                        </a>
                      )}
                      {sourceSnippet ? (
                        <blockquote className="mt-2 pl-3 border-l-2 border-accent/40 text-sm text-txt/80 leading-relaxed italic">
                          &ldquo;
                          <HighlightedText text={sourceSnippet} shared={shared} />
                          &rdquo;
                        </blockquote>
                      ) : (
                        <p className="mt-2 text-xs text-muted italic">
                          Source excerpt unavailable. Open the link to compare.
                        </p>
                      )}
                      {isUrl && (
                        <a
                          href={passage.source}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-accent-l hover:text-accent bg-accent/10 hover:bg-accent/15 rounded-lg transition-colors"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                          View full source
                        </a>
                      )}
                    </div>
                  </div>
                  {/* Why was this flagged? */}
                  <details className="px-4 pb-3 pt-1 group">
                    <summary className="text-xs text-muted cursor-pointer select-none hover:text-txt transition-colors">
                      Why was this flagged?
                    </summary>
                    <div className="mt-2 text-xs text-txt/70 space-y-1 pl-3 border-l border-border/40">
                      <p>{explanation}</p>
                      {chip && (
                        <p className="text-muted">
                          Match kind: <span className="text-txt/80">{chip.label}</span> — {chip.tooltip}
                        </p>
                      )}
                      <p className="text-muted">
                        Similarity: {pct.toFixed(0)}% &middot; Severity: {band.label.toLowerCase()}
                      </p>
                      {shared.size > 0 && (
                        <p className="text-muted">
                          Highlighted: {shared.size} shared 3-word phrase
                          {shared.size === 1 ? "" : "s"} between your text and the source excerpt.
                        </p>
                      )}
                    </div>
                  </details>
                </div>
              );
            })}
          </div>
        </Card>
      ) : (
        <EmptyState
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
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({
  allPassagesEmpty,
  selectedSource,
  onClearFilter,
  emptyReason,
}: {
  allPassagesEmpty: boolean;
  selectedSource: string | null;
  onClearFilter: () => void;
  emptyReason: AnalysisResult["empty_reason"];
}) {
  // Filter active but no passages for that source — distinct from "nothing flagged".
  if (!allPassagesEmpty && selectedSource) {
    return (
      <Card>
        <div className="text-center py-8 space-y-3">
          <Search className="w-8 h-8 text-muted mx-auto" />
          <p className="text-sm text-txt">
            No flagged passages match the source you selected.
          </p>
          <button
            onClick={onClearFilter}
            className="text-xs text-accent-l hover:text-accent"
          >
            Show all passages
          </button>
        </div>
      </Card>
    );
  }

  // No flagged passages at all — branch on backend explanation.
  let icon = <ShieldCheck className="w-8 h-8 text-emerald-400 mx-auto" />;
  let headline = "No matches found";
  let detail =
    "We scanned external sources and didn't find anything that crossed our reporting threshold.";

  if (emptyReason === "weak_only") {
    icon = <Info className="w-8 h-8 text-sky-400 mx-auto" />;
    headline = "Weak signals only";
    detail =
      "We found candidate sources, but none had enough shared rare phrasing to flag. Common topic overlap can produce these signals — they aren't evidence of copying.";
  } else if (emptyReason === "no_corpus") {
    icon = <FileX className="w-8 h-8 text-amber-400 mx-auto" />;
    headline = "No comparison corpus";
    detail =
      "Search providers returned nothing for this document. This usually means a transient outage, or that the content is too short or specialised to retrieve candidates. Try again later.";
  }

  return (
    <Card>
      <div className="text-center py-8 space-y-3">
        {icon}
        <p className="text-base font-semibold text-txt">{headline}</p>
        <p className="text-sm text-muted max-w-md mx-auto leading-relaxed">
          {detail}
        </p>
      </div>
    </Card>
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
}: {
  label: string;
  score: number;
  icon: React.ReactNode;
  tooltip?: string;
}) {
  const value = score ?? 0;
  return (
    <div
      className="bg-surface border border-border rounded-2xl p-4 flex flex-col items-center"
      title={tooltip}
    >
      <div className={`mb-1 ${scoreColor(value)}`}>{icon}</div>
      <div className={`text-3xl font-bold ${scoreColor(value)}`}>
        {value.toFixed(0)}%
      </div>
      <div className="text-xs text-muted mt-1 text-center max-w-[14ch]">
        {label}
      </div>
    </div>
  );
}
