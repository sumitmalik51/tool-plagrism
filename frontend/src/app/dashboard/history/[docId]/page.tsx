"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Download,
  Clock,
  ExternalLink,
  Info,
  Pencil,
  Bot,
  AlertTriangle,
  Globe,
  BookOpen,
  Sparkles,
  Plus,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { formatDate, scoreColor, cn, RISK_TOOLTIP } from "@/lib/utils";
import { Button, Badge, Spinner, Tabs } from "@/components/ui";
import type { AnalysisResult, DetectedSource, FlaggedPassage } from "@/lib/types";
import {
  PassageCard as SharedPassageCard,
  PassagesEmptyState,
  AdjustedScorePill,
  useSourcesByUrl,
} from "@/components/passage-shared";
import {
  useDismissalsStore,
  adjustedScore,
} from "@/lib/stores/dismissals-store";

/* ─── Types ──────────────────────────────────────────────── */

interface MatchGroup {
  category: string;
  icon: string;
  count: number;
  percentage: number;
}

interface ScanDetail {
  id: number;
  document_id: string;
  plagiarism_score: number;
  confidence_score: number;
  risk_level: string;
  sources_count: number;
  flagged_count: number;
  created_at: string;
  filename?: string;
  report_json: AnalysisResult & {
    original_text?: string;
    language_name?: string;
    match_groups?: MatchGroup[];
    explanation?: string;
  };
}

interface Revision {
  id: number;
  document_id: string;
  plagiarism_score: number;
  confidence_score: number;
  risk_level: string;
  sources_count: number;
  flagged_count: number;
  created_at: string;
}

/* ─── Helpers ────────────────────────────────────────────── */

function riskVariant(risk: string): "success" | "warning" | "danger" {
  switch ((risk || "").toUpperCase()) {
    case "LOW":
      return "success";
    case "MEDIUM":
      return "warning";
    default:
      return "danger";
  }
}

function sourceTypeVariant(type: string): "accent" | "danger" | "default" {
  const t = (type || "").toLowerCase();
  if (t.includes("internet") || t.includes("web")) return "accent";
  if (t.includes("publication") || t.includes("paper") || t.includes("journal") || t.includes("doi"))
    return "danger";
  return "default";
}

function resolveSourceName(src: DetectedSource): string {
  if (src.title && src.title !== "Untitled" && src.title.length > 2) return src.title;
  if (!src.url) return "Unknown Source";
  try {
    const host = new URL(src.url).hostname.replace(/^www\./, "");
    return host
      .split(".")
      .slice(0, -1)
      .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
      .join(" ");
  } catch {
    return src.url.slice(0, 60);
  }
}

/* ─── Category config for breakdown bars ─────────────────── */

interface CatCfg {
  icon: React.ReactNode;
  barColor: string;
  labelColor: string;
}
const CAT_CFG: Record<string, CatCfg> = {
  "Internet Matches": {
    icon: <Globe className="w-4 h-4" />,
    barColor: "bg-danger",
    labelColor: "text-danger",
  },
  "Research Papers": {
    icon: <BookOpen className="w-4 h-4" />,
    barColor: "bg-accent",
    labelColor: "text-accent",
  },
  "AI Generated Content": {
    icon: <Sparkles className="w-4 h-4" />,
    barColor: "bg-warn",
    labelColor: "text-warn",
  },
  "Paraphrased Similarity": {
    icon: <Plus className="w-4 h-4" />,
    barColor: "bg-warn",
    labelColor: "text-warn",
  },
};
function getCatCfg(cat: string): CatCfg {
  return (
    CAT_CFG[cat] || {
      icon: <Globe className="w-4 h-4" />,
      barColor: "bg-muted",
      labelColor: "text-muted",
    }
  );
}

/* ─── Donut Chart ────────────────────────────────────────── */

function DonutChart({
  webPct,
  paraphrasePct,
  originalPct,
}: {
  webPct: number;
  paraphrasePct: number;
  originalPct: number;
}) {
  const seg1 = webPct;
  const seg2 = webPct + paraphrasePct;
  return (
    <div className="bg-surface border border-border rounded-2xl p-6 flex flex-col items-center">
      <p className="text-xs tracking-[0.2em] text-muted uppercase mb-3">
        Original
      </p>
      <div className="relative w-40 h-40">
        <div
          className="w-full h-full rounded-full"
          style={{
            background: `conic-gradient(var(--danger) 0% ${seg1}%, var(--warn) ${seg1}% ${seg2}%, var(--ok) ${seg2}% 100%)`,
            mask: "radial-gradient(circle at center, transparent 55%, black 56%)",
            WebkitMask:
              "radial-gradient(circle at center, transparent 55%, black 56%)",
          }}
        />
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold text-ok">{originalPct}%</span>
          <span className="text-xs text-muted">original</span>
        </div>
      </div>
      <div className="mt-4 space-y-1 text-sm self-start">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-danger" />
          <span className="text-muted">Web match {webPct}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-warn" />
          <span className="text-muted">Paraphrase {paraphrasePct}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-ok" />
          <span className="text-muted">Original {originalPct}%</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Source Card ─────────────────────────────────────────── */

function SourceCard({ src }: { src: DetectedSource }) {
  const similarity = (src.similarity ?? 0) * 100;
  const name = resolveSourceName(src);
  return (
    <div className="bg-surface border border-border rounded-xl p-4 hover:border-accent/30 transition-colors">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className={`text-lg font-bold ${scoreColor(similarity)}`}>
              {similarity.toFixed(1)}%
            </span>
            <Badge variant={sourceTypeVariant(src.source_type)}>
              {src.source_type || "Internet"}
            </Badge>
            <span className="text-xs text-muted">
              {src.matched_words ?? 0} words matched across{" "}
              {src.text_blocks ?? 0} passage
              {(src.text_blocks ?? 0) !== 1 ? "s" : ""}
            </span>
          </div>
          <p className="text-sm font-medium text-txt mb-1">{name}</p>
          {src.url && (
            <a
              href={src.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-accent-l hover:text-accent break-all"
            >
              {src.url.length > 70 ? src.url.slice(0, 70) + "…" : src.url}
            </a>
          )}
        </div>
        {src.url && (
          <a
            href={src.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 flex items-center gap-1 px-3 py-1.5 bg-surface2 hover:bg-border text-sm text-muted hover:text-txt rounded-lg border border-border transition-colors"
          >
            Compare <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>
    </div>
  );
}

/* ─── Rewrite action slot ─────────────────────────────────── */

function RewriteActions({
  busy,
  variations,
  onRewrite,
}: {
  busy: boolean;
  variations?: string[];
  onRewrite: (mode: string) => void;
}) {
  return (
    <span className="inline-flex flex-col items-stretch gap-2 w-full">
      <span className="inline-flex items-center gap-2 flex-wrap">
        <button
          disabled={busy}
          onClick={() => onRewrite("paraphrase")}
          className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-medium text-muted hover:text-txt bg-surface2 hover:bg-border rounded-lg border border-border transition-colors disabled:opacity-50"
        >
          <Pencil className="w-3 h-3" />
          Rewrite
        </button>
        <button
          disabled={busy}
          onClick={() => onRewrite("humanize")}
          className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-medium text-muted hover:text-txt bg-surface2 hover:bg-border rounded-lg border border-border transition-colors disabled:opacity-50"
        >
          <Bot className="w-3 h-3" />
          Humanize
        </button>
        {busy && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
            <span className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            Processing…
          </span>
        )}
      </span>
      {variations && variations.length > 0 && (
        <span className="block space-y-2 w-full">
          <span className="block text-[11px] font-medium text-ok">
            ✓ {variations.length} variation
            {variations.length !== 1 ? "s" : ""} generated
          </span>
          {variations.map((v, vi) => (
            <span
              key={vi}
              className="block p-3 bg-ok/5 border border-ok/20 rounded-xl group"
            >
              <span className="flex items-start justify-between gap-2">
                <span className="text-sm text-txt/80 leading-relaxed flex-1 whitespace-pre-wrap">
                  {v}
                </span>
                <button
                  onClick={() => navigator.clipboard.writeText(v)}
                  className="shrink-0 px-2 py-1 text-xs text-muted hover:text-ok bg-surface2 hover:bg-ok/10 rounded-md border border-border transition-colors opacity-0 group-hover:opacity-100"
                >
                  Copy
                </button>
              </span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

/* ─── Main Page ──────────────────────────────────────────── */

type SourceFilter = "all" | "internet" | "publications" | "high";
type SourceSort = "similarity" | "words";

export default function ScanDetailPage() {
  const { docId } = useParams<{ docId: string }>();
  const router = useRouter();
  const toast = useToastStore();

  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("sources");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [sourceSort, setSourceSort] = useState<SourceSort>("similarity");
  const [showAllSources, setShowAllSources] = useState(false);
  const [rewritingIdx, setRewritingIdx] = useState<number | null>(null);
  const [rewrittenTexts, setRewrittenTexts] = useState<Record<number, string[]>>(
    {},
  );

  /* ── Data fetch ── */
  useEffect(() => {
    if (!docId) return;
    setLoading(true);
    Promise.all([
      api.get(`/api/v1/auth/scans/${docId}`),
      api
        .get(`/api/v1/auth/scans/${docId}/revisions`)
        .catch(() => ({ data: { revisions: [] } })),
    ])
      .then(([scanRes, revRes]) => {
        setScan(scanRes.data);
        setRevisions(revRes.data.revisions || []);
      })
      .catch(() => toast.add("error", "Failed to load scan details."))
      .finally(() => setLoading(false));
  }, [docId, toast]);

  /* ── Parse report_json (may be string or object from DB) ── */
  const report = useMemo<ScanDetail["report_json"]>(() => {
    if (!scan) return {} as ScanDetail["report_json"];
    const raw: unknown = scan.report_json;
    if (typeof raw === "string" && (raw as string).trim()) {
      try {
        return JSON.parse(raw as string);
      } catch {
        return {} as ScanDetail["report_json"];
      }
    }
    if (raw && typeof raw === "object") return raw as ScanDetail["report_json"];
    return {} as ScanDetail["report_json"];
  }, [scan]);

  /* ── Derived values ── */
  const plagiarismScore =
    scan?.plagiarism_score ?? report.plagiarism_score ?? 0;
  const confidenceScore =
    scan?.confidence_score ?? report.confidence_score ?? 0;
  const riskLevel = (
    scan?.risk_level ??
    report.risk_level ??
    "LOW"
  ).toUpperCase();
  const sources: DetectedSource[] = useMemo(
    () => report.detected_sources ?? [],
    [report.detected_sources],
  );
  const passages: FlaggedPassage[] = useMemo(
    () => report.flagged_passages ?? [],
    [report.flagged_passages],
  );
  const matchGroups: MatchGroup[] = useMemo(
    () => report.match_groups ?? [],
    [report.match_groups],
  );

  // O(1) source lookup by URL — used inside the passages map.
  const sourcesByUrl = useSourcesByUrl(sources);

  // Per-document dismissals + adjusted score.
  const dismissedForDoc = useDismissalsStore(
    (s) => s.dismissed[docId],
  );
  const clearAllDismissals = useDismissalsStore((s) => s.clearAll);
  const dismissedCount = dismissedForDoc
    ? Object.keys(dismissedForDoc).length
    : 0;
  const adjusted = useMemo(
    () => adjustedScore(plagiarismScore, passages, dismissedForDoc),
    [plagiarismScore, passages, dismissedForDoc],
  );

  const webPct = useMemo(() => {
    const g = matchGroups.find((m) => m.category === "Internet Matches");
    return g
      ? Math.round(g.percentage * 10) / 10
      : Math.round(plagiarismScore * 0.35 * 10) / 10;
  }, [matchGroups, plagiarismScore]);

  const paraphrasePct = useMemo(() => {
    const g = matchGroups.find((m) => m.category === "Paraphrased Similarity");
    return g
      ? Math.round(g.percentage * 10) / 10
      : Math.round(plagiarismScore * 0.65 * 10) / 10;
  }, [matchGroups, plagiarismScore]);

  const originalPct = Math.max(
    0,
    Math.round((100 - plagiarismScore) * 10) / 10,
  );

  /* ── Filtered + sorted sources ── */
  const filteredSources = useMemo(() => {
    let list = [...sources];
    if (sourceFilter === "internet")
      list = list.filter((s) =>
        (s.source_type || "").toLowerCase().includes("internet"),
      );
    else if (sourceFilter === "publications")
      list = list.filter((s) => {
        const t = (s.source_type || "").toLowerCase();
        return (
          t.includes("publication") ||
          t.includes("paper") ||
          t.includes("journal")
        );
      });
    else if (sourceFilter === "high")
      list = list.filter((s) => (s.similarity ?? 0) >= 0.75);

    list.sort((a, b) =>
      sourceSort === "similarity"
        ? (b.similarity ?? 0) - (a.similarity ?? 0)
        : (b.matched_words ?? 0) - (a.matched_words ?? 0),
    );
    return list;
  }, [sources, sourceFilter, sourceSort]);

  const visibleSources = showAllSources
    ? filteredSources
    : filteredSources.slice(0, 4);

  /* ── PDF download ── */
  const downloadPdf = useCallback(async () => {
    try {
      const res = await api.get(`/api/v1/export-pdf/${docId}`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `plagiarism-report-${docId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.add("success", "Report downloaded!");
    } catch {
      toast.add("error", "Failed to download report.");
    }
  }, [docId, toast]);

  /* ── Passage rewrite handler ── */
  const handleRewrite = useCallback(
    async (text: string, mode: string, idx: number) => {
      setRewritingIdx(idx);
      try {
        const res = await api.post("/api/v1/rewrite/general", {
          text,
          mode,
          tone: "neutral",
          strength: "medium",
        });
        const variations: string[] = res.data.variations ?? [];
        if (variations.length === 0) {
          toast.add("warning", "No variations returned.");
          return;
        }
        setRewrittenTexts((prev) => ({
          ...prev,
          [idx]: variations,
        }));
        toast.add(
          "success",
          `${variations.length} variation${variations.length !== 1 ? "s" : ""} ready — pick one below!`,
        );
      } catch {
        toast.add("error", `Failed to ${mode} text.`);
      } finally {
        setRewritingIdx(null);
      }
    },
    [toast],
  );

  /* ─── Render ───────────────────────────────────────────── */

  if (loading)
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );

  if (!scan)
    return (
      <div className="text-center py-24 text-muted">
        <p>Scan not found.</p>
        <Button
          variant="secondary"
          className="mt-4"
          onClick={() => router.push("/dashboard/history")}
        >
          Back to History
        </Button>
      </div>
    );

  const filename =
    scan.filename || scan.document_id.slice(0, 40) + "…";

  return (
    <div className="max-w-6xl mx-auto pb-16">
      {/* ── Sticky Header Bar ── */}
      <div className="sticky top-0 z-40 bg-bg/80 backdrop-blur-xl border-b border-border -mx-4 px-4 py-3 mb-6 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => router.push("/dashboard/history")}
            className="flex items-center gap-1 text-sm text-accent-l hover:text-accent transition-colors shrink-0"
          >
            <ArrowLeft className="w-4 h-4" /> History
          </button>
          <span className="text-border">|</span>
          <span className="text-sm text-txt truncate max-w-[300px] sm:max-w-[400px]">
            {filename}
          </span>
          <span
            className={`text-lg font-bold ${scoreColor(plagiarismScore)}`}
          >
            {Math.round(plagiarismScore)}%
          </span>
          <span title={RISK_TOOLTIP}>
            <Badge variant={riskVariant(riskLevel)}>{riskLevel} Risk</Badge>
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <AdjustedScorePill
            original={plagiarismScore}
            adjusted={adjusted}
            dismissedCount={dismissedCount}
            onReset={() => clearAllDismissals(docId)}
          />
          <Button variant="secondary" size="sm" onClick={downloadPdf}>
            <Download className="w-4 h-4" />
            Download PDF
          </Button>
        </div>
      </div>

      {/* ── Hero Section: Score + Breakdown ── */}
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 mb-6">
        {/* Left column */}
        <div className="space-y-6">
          {/* Overall Plagiarism */}
          <div className="bg-surface border border-border rounded-2xl p-6 text-center">
            <p className="text-xs tracking-[0.2em] text-muted uppercase mb-3">
              Overall Plagiarism
            </p>
            <p
              className={`text-6xl font-extrabold leading-none ${scoreColor(plagiarismScore)}`}
            >
              {Math.round(plagiarismScore)}%
            </p>
            <div className="mt-3" title={RISK_TOOLTIP}>
              <Badge
                variant={riskVariant(riskLevel)}
                className="text-sm px-3 py-1"
              >
                <AlertTriangle className="w-3 h-3 mr-1" />
                {riskLevel} Risk
              </Badge>
              <details className="mt-1 text-[10px] text-muted/80">
                <summary className="cursor-pointer hover:text-txt">
                  Risk thresholds
                </summary>
                <p className="mt-1 leading-snug max-w-[28ch] mx-auto">
                  {RISK_TOOLTIP}
                </p>
              </details>
            </div>
            {/* Confidence with tooltip */}
            <div className="mt-3 relative group inline-flex items-center gap-1 text-sm text-muted">
              Confidence: {Math.round(confidenceScore)}%
              <Info className="w-3.5 h-3.5 cursor-help" />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block w-56 p-3 bg-surface2 border border-border rounded-xl text-xs text-txt shadow-xl z-10 text-left">
                Based on multi-agent analysis consensus. Higher confidence means
                stronger agreement between detection methods.
              </div>
            </div>
          </div>

          {/* Donut chart */}
          <DonutChart
            webPct={webPct}
            paraphrasePct={paraphrasePct}
            originalPct={originalPct}
          />
        </div>

        {/* Right column: Score Breakdown */}
        <div className="bg-surface border border-border rounded-2xl p-6">
          <p className="text-sm text-muted mb-6">
            Score breakdown —{" "}
            {matchGroups.length > 0
              ? `${matchGroups.length}-agent`
              : "multi-agent"}{" "}
            consensus
          </p>
          <div className="space-y-5">
            {matchGroups.length > 0 ? (
              matchGroups.map((g, i) => {
                const cfg = getCatCfg(g.category);
                return (
                  <div key={i}>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <div
                          className={cn(
                            "p-1.5 rounded-lg bg-surface2",
                            cfg.labelColor,
                          )}
                        >
                          {cfg.icon}
                        </div>
                        <span className="text-sm font-medium text-txt">
                          {g.category}
                        </span>
                      </div>
                      <span
                        className={cn("text-sm font-semibold", cfg.labelColor)}
                      >
                        {(g.percentage ?? 0).toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2.5 bg-surface2 rounded-full overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all duration-700",
                          cfg.barColor,
                        )}
                        style={{
                          width: `${Math.max(Math.min(g.percentage ?? 0, 100), 0.5)}%`,
                        }}
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="text-sm text-muted space-y-1">
                <p>Plagiarism: {plagiarismScore.toFixed(1)}%</p>
                <p>Original: {originalPct}%</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Action Callout ── */}
      {plagiarismScore > 0 && (
        <div className="mb-6 bg-warn/10 border border-warn/30 rounded-xl px-5 py-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-warn shrink-0 mt-0.5" />
          <p className="text-sm text-txt">
            <strong>
              {Math.round(plagiarismScore)}% of this document matched external
              sources.
            </strong>{" "}
            Review the {sources.length} flagged source
            {sources.length !== 1 ? "s" : ""} and {passages.length} highlighted
            passage{passages.length !== 1 ? "s" : ""} below before submission.
            Use the rewrite actions to fix flagged sections.
          </p>
        </div>
      )}

      {/* ── Tabs ── */}
      <Tabs
        tabs={[
          { id: "sources", label: `Detected Sources (${sources.length})` },
          { id: "passages", label: `Flagged Passages (${passages.length})` },
        ]}
        active={activeTab}
        onChange={setActiveTab}
        className="mb-4"
      />

      {/* ── Sources Tab ── */}
      {activeTab === "sources" && (
        <div className="space-y-4">
          {/* Filter + Sort bar */}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-muted">Filter:</span>
              {(
                [
                  { key: "all", label: `All (${sources.length})` },
                  { key: "internet", label: "Internet only" },
                  { key: "publications", label: "Publications only" },
                  { key: "high", label: "High similarity (>75%)" },
                ] as const
              ).map((f) => (
                <button
                  key={f.key}
                  onClick={() => {
                    setSourceFilter(f.key);
                    setShowAllSources(false);
                  }}
                  className={cn(
                    "px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors",
                    sourceFilter === f.key
                      ? "bg-accent/15 text-accent-l border-accent/30"
                      : "bg-surface2 text-muted border-border hover:text-txt",
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted">Sort:</span>
              <select
                value={sourceSort}
                onChange={(e) => setSourceSort(e.target.value as SourceSort)}
                className="bg-surface2 text-sm text-txt border border-border rounded-lg px-2 py-1.5 cursor-pointer"
              >
                <option value="similarity">Similarity ↓</option>
                <option value="words">Word count ↓</option>
              </select>
            </div>
          </div>

          {/* Source cards */}
          {filteredSources.length === 0 ? (
            <p className="text-center py-8 text-muted text-sm">
              No sources match this filter.
            </p>
          ) : (
            <>
              <div className="space-y-3">
                {visibleSources.map((src, i) => (
                  <SourceCard key={i} src={src} />
                ))}
              </div>
              {!showAllSources && filteredSources.length > 4 && (
                <button
                  onClick={() => setShowAllSources(true)}
                  className="block mx-auto text-sm text-accent-l hover:text-accent transition-colors mt-2"
                >
                  Show all {filteredSources.length} sources{" "}
                  <ExternalLink className="w-3.5 h-3.5 inline ml-1" />
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Passages Tab ── */}
      {activeTab === "passages" && (
        <div className="space-y-3">
          {passages.length === 0 ? (
            <PassagesEmptyState
              allPassagesEmpty={true}
              selectedSource={null}
              onClearFilter={() => {}}
              emptyReason={report.empty_reason ?? null}
            />
          ) : (
            passages.map((p, i) => {
              const matchedSource =
                (p.source && sourcesByUrl.get(p.source)) || undefined;
              return (
                <SharedPassageCard
                  key={i}
                  documentId={docId}
                  passage={p}
                  passageIndex={i}
                  matchedSource={matchedSource}
                  actions={
                    <RewriteActions
                      busy={rewritingIdx === i}
                      variations={rewrittenTexts[i]}
                      onRewrite={(mode) => handleRewrite(p.text, mode, i)}
                    />
                  }
                />
              );
            })
          )}
        </div>
      )}

      {/* ── Original Text (collapsible) ── */}
      {report.original_text && (
        <details className="mt-6 bg-surface border border-border rounded-2xl overflow-hidden">
          <summary className="px-6 py-4 cursor-pointer text-sm font-semibold text-muted hover:text-txt transition-colors">
            Original Text
          </summary>
          <div className="px-6 pb-6">
            <p className="text-sm text-txt/70 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
              {report.original_text}
            </p>
          </div>
        </details>
      )}

      {/* ── Revision History ── */}
      {revisions.length > 1 && (
        <div className="mt-6 bg-surface border border-border rounded-2xl p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Clock className="w-5 h-5 text-muted" />
            Revision History ({revisions.length})
          </h3>
          <div className="space-y-2">
            {revisions.map((rev) => (
              <div
                key={rev.id}
                onClick={() =>
                  router.push(`/dashboard/history/${rev.document_id}`)
                }
                className={cn(
                  "flex items-center justify-between p-3 rounded-xl cursor-pointer transition-colors",
                  rev.document_id === docId
                    ? "bg-accent/10 border border-accent/30"
                    : "bg-bg hover:bg-surface2",
                )}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted">
                    {formatDate(rev.created_at)}
                  </span>
                  <span
                    className={`text-sm font-semibold ${scoreColor(rev.plagiarism_score)}`}
                  >
                    {(rev.plagiarism_score ?? 0).toFixed(1)}%
                  </span>
                  <Badge variant={riskVariant(rev.risk_level)}>
                    {rev.risk_level}
                  </Badge>
                </div>
                <span className="text-xs text-muted">
                  {rev.sources_count} sources
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
