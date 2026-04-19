"use client";

/**
 * Shared building blocks for plagiarism passage UI. Both the live
 * Results panel (`components/Results.tsx`) and the saved-scan detail view
 * (`app/dashboard/history/[docId]/page.tsx`) render against the same
 * report shape; they should also render against the same components, or
 * the two surfaces will drift.
 */

import { useMemo, type ReactNode } from "react";
import {
  Equal,
  Sparkles,
  ExternalLink,
  ShieldCheck,
  Info,
  FileX,
  Search,
  Quote as QuoteIcon,
  UserCheck,
  XCircle,
  RotateCcw,
} from "lucide-react";
import Card from "@/components/ui/Card";
import { passageBand, passageExplanation } from "@/lib/utils";
import type {
  AnalysisResult,
  DetectedSource,
  FlaggedPassage,
} from "@/lib/types";
import {
  useDismissalsStore,
  dismissalLabel,
  type DismissalKind,
} from "@/lib/stores/dismissals-store";

// =====================================================================
// match_type chip
// =====================================================================

type MatchType = NonNullable<FlaggedPassage["match_type"]>;

interface MatchChipMeta {
  label: string;
  tooltip: string;
  /** Tailwind classes drawn from project tokens (text-danger / text-warn / text-accent). */
  className: string;
  symbol: ReactNode;
}

export function matchTypeMeta(
  t: MatchType | null | undefined,
): MatchChipMeta | null {
  switch (t) {
    case "exact":
      return {
        label: "Exact",
        tooltip: "Verbatim or near-verbatim overlap (long shared word run).",
        className: "bg-danger/10 text-danger border-danger/30",
        symbol: <Equal className="w-3 h-3" />,
      };
    case "paraphrase":
      return {
        label: "Paraphrase",
        tooltip:
          "Reworded text that still shares rare phrases with a candidate source.",
        className: "bg-warn/10 text-warn border-warn/30",
        symbol: (
          <span className="text-[11px] leading-none font-bold">≈</span>
        ),
      };
    case "semantic":
      return {
        label: "Semantic",
        tooltip:
          "Embedding-only similarity. No shared phrases — possibly the same idea, different words.",
        className: "bg-accent/10 text-accent-l border-accent/30",
        symbol: <Sparkles className="w-3 h-3" />,
      };
    default:
      return null;
  }
}

export function MatchTypeChip({
  matchType,
}: {
  matchType: MatchType | null | undefined;
}) {
  const meta = matchTypeMeta(matchType);
  if (!meta) return null;
  return (
    <span
      title={meta.tooltip}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border rounded ${meta.className}`}
    >
      {meta.symbol}
      {meta.label}
    </span>
  );
}

// =====================================================================
// Trigram overlap helpers (Unicode-aware)
// =====================================================================

/**
 * Tokenize preserving spacing: [word, separator, word, separator, …]
 * The /u flag makes \w match Unicode word characters across scripts
 * (Hindi, Cyrillic, Greek, etc.). CJK languages don't use whitespace,
 * so they degrade to a per-character word and trigram overlap there
 * is meaningless — for those, we simply produce no highlights.
 */
export function tokenize(text: string): string[] {
  return text.match(/\w+|\W+/gu) ?? [];
}

function wordList(text: string): string[] {
  return (text.toLowerCase().match(/\w+/gu) ?? []).filter(Boolean);
}

/** Build the set of 3-word phrases that appear in `b` and also in `a`. */
export function sharedTrigramSet(a: string, b: string): Set<string> {
  const wordsA = wordList(a);
  const wordsB = wordList(b);
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

/** Union of shared trigrams across multiple candidate snippets. */
export function unionTrigramSets(
  passageText: string,
  snippets: string[],
): Set<string> {
  const out = new Set<string>();
  for (const s of snippets) {
    if (!s) continue;
    const sub = sharedTrigramSet(passageText, s);
    sub.forEach((t) => out.add(t));
  }
  return out;
}

// =====================================================================
// Highlighted text renderer
// =====================================================================

/**
 * Render `text`, wrapping any word that participates in a shared 3-gram
 * (with `shared`) in a <mark>. Adjacent highlighted runs are coalesced
 * into a single span so the output reads as phrases, not islands.
 */
export function HighlightedText({
  text,
  shared,
  highlightClass = "bg-warn/20 text-warn rounded px-0.5",
}: {
  text: string;
  shared: Set<string>;
  highlightClass?: string;
}) {
  if (!shared || shared.size === 0 || !text) {
    return <>{text}</>;
  }
  const tokens = tokenize(text);
  const wordIdx: number[] = [];
  tokens.forEach((tok, i) => {
    if (/\w/u.test(tok)) wordIdx.push(i);
  });
  const words = wordIdx.map((i) => tokens[i].toLowerCase());
  const highlightWord = new Array(wordIdx.length).fill(false);
  for (let i = 0; i <= words.length - 3; i++) {
    const tri = `${words[i]} ${words[i + 1]} ${words[i + 2]}`;
    if (shared.has(tri)) {
      highlightWord[i] = true;
      highlightWord[i + 1] = true;
      highlightWord[i + 2] = true;
    }
  }
  const tokenHl = new Array(tokens.length).fill(false);
  wordIdx.forEach((tokI, wI) => {
    if (highlightWord[wI]) tokenHl[tokI] = true;
  });
  // Coalesce: bridge a single separator token between two highlighted words.
  const out: ReactNode[] = [];
  let i = 0;
  while (i < tokens.length) {
    if (tokenHl[i]) {
      let j = i;
      while (j < tokens.length) {
        if (tokenHl[j]) {
          j++;
          continue;
        }
        if (
          !/\w/u.test(tokens[j]) &&
          j + 1 < tokens.length &&
          tokenHl[j + 1]
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

// =====================================================================
// Sources-by-URL Map (avoid O(N×M) lookup in passage map)
// =====================================================================

export function useSourcesByUrl(
  sources: DetectedSource[] | undefined,
): Map<string, DetectedSource> {
  return useMemo(() => {
    const m = new Map<string, DetectedSource>();
    (sources ?? []).forEach((s) => {
      if (s.url && !m.has(s.url)) m.set(s.url, s);
    });
    return m;
  }, [sources]);
}

// =====================================================================
// Passage card
// =====================================================================

interface PassageCardProps {
  documentId: string;
  passage: FlaggedPassage;
  passageIndex: number;
  matchedSource?: DetectedSource;
  /** Optional render slot for additional actions (e.g. Rewrite buttons). */
  actions?: ReactNode;
}

export function PassageCard({
  documentId,
  passage,
  passageIndex,
  matchedSource,
  actions,
}: PassageCardProps) {
  const dismissalKind = useDismissalsStore((s) =>
    s.dismissed[documentId]?.[passageIndex],
  );
  const dismiss = useDismissalsStore((s) => s.set);
  const undismiss = useDismissalsStore((s) => s.clear);

  const pct = (passage.similarity_score ?? 0) * 100;
  const band = passageBand(pct);
  const isUrl =
    !!passage.source &&
    (passage.source.startsWith("http://") ||
      passage.source.startsWith("https://"));
  const sourceTitle = matchedSource?.title || passage.source || "Unknown";
  const sourceType =
    matchedSource?.source_type || (isUrl ? "Internet" : "Unknown source");
  const explanation = passageExplanation(passage.reason, pct);
  const matchedSnippets =
    matchedSource?.matched_passages?.map((p) => p.text).filter(Boolean) ?? [];

  // Memoize: this can run for 50+ passages on every render otherwise.
  const shared = useMemo(
    () =>
      matchedSnippets.length
        ? unionTrigramSets(passage.text, matchedSnippets)
        : new Set<string>(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [passage.text, matchedSnippets.join("\u0001")],
  );

  const chip = matchTypeMeta(passage.match_type);
  const dismissed = dismissalKind !== undefined;

  return (
    <div
      className={`border-l-4 ${band.borderClass} ${band.bgClass} rounded-r-xl overflow-hidden ${
        dismissed ? "opacity-60" : ""
      }`}
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
        <MatchTypeChip matchType={passage.match_type} />
        {dismissed && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium border border-ok/40 bg-ok/10 text-ok rounded">
            Dismissed: {dismissalLabel[dismissalKind!]}
            <button
              onClick={() => undismiss(documentId, passageIndex)}
              title="Undo dismissal"
              className="hover:text-txt"
            >
              <RotateCcw className="w-3 h-3" />
            </button>
          </span>
        )}
      </div>
      {/* Side-by-side */}
      <div className="grid grid-cols-1 md:grid-cols-2">
        {/* Left: user document */}
        <div className="px-4 py-3 md:border-r md:border-border/30">
          <div className="flex items-center gap-1.5 mb-1.5">
            <div className={`w-2 h-2 rounded-full ${band.dotClass}`} />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">
              Your document
            </span>
          </div>
          <p className="text-sm text-txt/80 leading-relaxed">
            <HighlightedText text={passage.text} shared={shared} />
          </p>
        </div>
        {/* Right: source */}
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
              {passage.source!.length > 80
                ? passage.source!.slice(0, 80) + "…"
                : passage.source}
            </a>
          )}
          {matchedSnippets.length > 0 ? (
            <blockquote className="mt-2 pl-3 border-l-2 border-accent/40 text-sm text-txt/80 leading-relaxed italic">
              “
              <HighlightedText text={matchedSnippets[0]} shared={shared} />
              ”
              {matchedSnippets.length > 1 && (
                <span className="block mt-1 text-[10px] not-italic text-muted">
                  + {matchedSnippets.length - 1} more excerpt
                  {matchedSnippets.length === 2 ? "" : "s"} from this source
                </span>
              )}
            </blockquote>
          ) : passage.match_type === "semantic" ? (
            <p className="mt-2 text-xs text-muted italic">
              No surface overlap by design — this is an embedding-similarity
              signal. Open the source to compare meaning, not phrasing.
            </p>
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
      {/* Why was this flagged + dismissal actions */}
      <details className="px-4 pb-3 pt-1 group">
        <summary className="text-xs text-muted cursor-pointer select-none hover:text-txt transition-colors">
          Why was this flagged?
        </summary>
        <div className="mt-2 text-xs text-txt/70 space-y-1 pl-3 border-l border-border/40">
          <p>{explanation}</p>
          {chip && (
            <p className="text-muted">
              Match kind:{" "}
              <span className="text-txt/80">{chip.label}</span> — {chip.tooltip}
            </p>
          )}
          <p className="text-muted">
            Similarity: {pct.toFixed(0)}% · Severity:{" "}
            {band.label.toLowerCase()}
          </p>
          {shared.size > 0 && (
            <p className="text-muted">
              Highlighted: {shared.size} shared 3-word phrase
              {shared.size === 1 ? "" : "s"} between your text and the source
              excerpt
              {matchedSnippets.length > 1
                ? `s (across ${matchedSnippets.length} excerpts)`
                : ""}
              .
            </p>
          )}
        </div>
      </details>
      {/* Action row */}
      <div className="flex items-center gap-2 flex-wrap px-4 pb-3 pt-1 border-t border-border/20">
        <span className="text-[10px] uppercase tracking-wide text-muted mr-1">
          This match is:
        </span>
        <DismissButton
          kind="quotation"
          icon={<QuoteIcon className="w-3 h-3" />}
          label="Quotation"
          tooltip="I quoted this with proper citation."
          activeKind={dismissalKind}
          onClick={() => dismiss(documentId, passageIndex, "quotation")}
        />
        <DismissButton
          kind="prior_work"
          icon={<UserCheck className="w-3 h-3" />}
          label="My prior work"
          tooltip="This is my own previously published material."
          activeKind={dismissalKind}
          onClick={() => dismiss(documentId, passageIndex, "prior_work")}
        />
        <DismissButton
          kind="false_positive"
          icon={<XCircle className="w-3 h-3" />}
          label="Not a match"
          tooltip="The source isn't actually similar — common topic only."
          activeKind={dismissalKind}
          onClick={() => dismiss(documentId, passageIndex, "false_positive")}
        />
        {actions && (
          <span className="ml-auto inline-flex items-center gap-2 flex-wrap">
            {actions}
          </span>
        )}
      </div>
    </div>
  );
}

function DismissButton({
  kind,
  icon,
  label,
  tooltip,
  activeKind,
  onClick,
}: {
  kind: DismissalKind;
  icon: ReactNode;
  label: string;
  tooltip: string;
  activeKind: DismissalKind | undefined;
  onClick: () => void;
}) {
  const active = activeKind === kind;
  return (
    <button
      onClick={onClick}
      title={tooltip}
      aria-pressed={active}
      className={`inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium border rounded-lg transition-colors ${
        active
          ? "bg-ok/15 text-ok border-ok/40"
          : "bg-surface2 text-muted border-border hover:text-txt hover:bg-border"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

// =====================================================================
// Empty state (three branches)
// =====================================================================

export function PassagesEmptyState({
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

  let icon = <ShieldCheck className="w-8 h-8 text-ok mx-auto" />;
  let headline = "No matches found";
  let detail =
    "We scanned external sources and didn't find anything that crossed our reporting threshold.";

  if (emptyReason === "weak_only") {
    icon = <Info className="w-8 h-8 text-accent-l mx-auto" />;
    headline = "Weak signals only";
    detail =
      "We found candidate sources, but none had enough shared rare phrasing to flag. Common topic overlap can produce these signals — they aren't evidence of copying.";
  } else if (emptyReason === "no_corpus") {
    icon = <FileX className="w-8 h-8 text-warn mx-auto" />;
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

// =====================================================================
// Adjusted-score pill
// =====================================================================

export function AdjustedScorePill({
  original,
  adjusted,
  dismissedCount,
  onReset,
}: {
  original: number;
  adjusted: number;
  dismissedCount: number;
  onReset: () => void;
}) {
  if (dismissedCount === 0 || Math.abs(adjusted - original) < 0.05) return null;
  return (
    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-ok/30 bg-ok/5 text-xs">
      <span className="text-muted">After {dismissedCount} dismissal{dismissedCount === 1 ? "" : "s"}:</span>
      <span className="font-semibold text-ok">Adjusted {adjusted.toFixed(0)}%</span>
      <span className="text-muted">(was {original.toFixed(0)}%)</span>
      <button
        onClick={onReset}
        title="Undo all dismissals"
        className="ml-1 text-muted hover:text-txt"
      >
        <RotateCcw className="w-3 h-3" />
      </button>
    </div>
  );
}
