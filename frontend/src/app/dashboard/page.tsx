"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import {
  Search,
  Upload,
  FileText,
  Link as LinkIcon,
  X,
  AlertCircle,
  Sparkles,
  ArrowRight,
  Clock,
  BookOpen,
  Globe,
  Bot,
  BarChart3,
  Zap,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { useScanJobsStore, type ScanJob } from "@/lib/stores/scan-jobs-store";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import ScanProgressBar from "@/components/ScanProgressBar";
import Results from "@/components/Results";
import type { AnalysisResult, UsageResponse } from "@/lib/types";
import { wordCount, formatDate } from "@/lib/utils";

type InputMode = "text" | "file" | "url";

const SAMPLE_TEXT = `The transformer architecture, introduced by Vaswani et al. in 2017, revolutionized natural language processing by replacing recurrent layers with self-attention mechanisms. This enabled parallel processing of sequences and dramatically improved performance on translation and language modeling tasks. Subsequent models such as BERT and GPT built upon this foundation, scaling both data and parameters to achieve state-of-the-art results across a wide range of benchmarks.`;

const AGENTS = [
  { name: "Semantic", icon: Sparkles, color: "text-violet-400" },
  { name: "Web Search", icon: Globe, color: "text-blue-400" },
  { name: "Academic", icon: BookOpen, color: "text-emerald-400" },
  { name: "AI Detection", icon: Bot, color: "text-amber-400" },
  { name: "Aggregation", icon: BarChart3, color: "text-rose-400" },
];

interface RecentScan {
  id: number;
  document_id: string;
  plagiarism_score: number;
  risk_level: string;
  sources_count: number;
  flagged_count: number;
  created_at: string;
  filename?: string;
}

function riskTone(risk: string) {
  switch ((risk || "").toUpperCase()) {
    case "LOW":
      return "success" as const;
    case "MEDIUM":
      return "warning" as const;
    default:
      return "danger" as const;
  }
}

export default function AnalyzerPage() {
  const [mode, setMode] = useState<InputMode>("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [googleUrl, setGoogleUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<RecentScan[]>([]);
  const [usage, setUsage] = useState<UsageResponse | null>(null);

  const toast = useToastStore();
  const activeJob = useScanJobsStore((s) => s.active);
  const setActiveJob = useScanJobsStore((s) => s.setActive);
  const clearActiveJob = useScanJobsStore((s) => s.clearActive);

  // When the active job finishes, lift its result onto the page and toast.
  useEffect(() => {
    if (!activeJob) return;
    if (activeJob.status === "completed" && activeJob.result) {
      setResult(activeJob.result);
      toast.add("success", "Analysis complete!");
      // Refresh usage counters after scan completes
      api.get("/api/v1/auth/usage").then((r) => setUsage(r.data)).catch(() => {});
    } else if (activeJob.status === "failed") {
      setError(activeJob.error || "Analysis failed. Please try again.");
      toast.add("error", activeJob.error || "Analysis failed.");
    }
    // We only react to status transitions, not every tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJob?.status]);

  const isRunning =
    !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const loading = submitting || isRunning;

  useEffect(() => {
    api
      .get("/api/v1/auth/scans", { params: { limit: 3, offset: 0 } })
      .then((r) => setRecent((r.data.scans || []).slice(0, 3)))
      .catch(() => {
        /* ignore — first-time user, or endpoint not available */
      });
    api
      .get("/api/v1/auth/usage")
      .then((r) => setUsage(r.data))
      .catch(() => {});
  }, []);

  const canSubmit =
    !loading &&
    ((mode === "text" && text.trim().length > 0) ||
      (mode === "file" && !!file) ||
      (mode === "url" && googleUrl.trim().length > 0));

  const handleAnalyze = async () => {
    setError("");
    setResult(null);

    if (!canSubmit) {
      if (mode === "text") {
        setError("Paste some text, upload a file, or import a Google Doc to begin.");
      } else if (mode === "file") {
        setError("Please select a file to upload.");
      } else {
        setError("Please enter a Google Docs URL.");
      }
      return;
    }

    setSubmitting(true);
    // Generate a doc_id up front so the SSE channel can be subscribed
    // immediately — file uploads can take 10s+ to ingest server-side.
    const preDocId =
      (typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)
      ).replace(/-/g, "");

    const previewLabel =
      mode === "file"
        ? file?.name || "File scan"
        : mode === "url"
          ? "Google Doc scan"
          : (text.trim().split("\n", 1)[0] || "Text scan").slice(0, 80);

    // Seed a placeholder job so the progress card shows up instantly.
    setActiveJob({
      job_id: `pending-${preDocId}`,
      document_id: preDocId,
      kind: mode === "file" ? "file" : mode === "url" ? "google_doc" : "text",
      label: previewLabel,
      status: "queued",
      created_at: Date.now() / 1000,
      started_at: Date.now() / 1000,
      completed_at: null,
      error: null,
      progress: {
        stage: mode === "file" ? "upload" : "queued",
        message:
          mode === "file"
            ? "Uploading and reading your document…"
            : "Preparing your scan…",
        percent: 2,
      },
    });

    try {
      let job: ScanJob;

      if (mode === "text") {
        if (wordCount(text) < 3) {
          setError("Please enter at least a few words to analyze.");
          setSubmitting(false);
          clearActiveJob();
          return;
        }
        const res = await api.post("/api/v1/jobs/analyze-text", {
          text,
          document_id: preDocId,
        });
        job = res.data as ScanJob;
      } else if (mode === "file") {
        const formData = new FormData();
        formData.append("file", file!);
        formData.append("document_id", preDocId);
        const res = await api.post("/api/v1/jobs/analyze-file", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        job = res.data as ScanJob;
      } else {
        const importRes = await api.post("/api/v1/import-google-doc", {
          url: googleUrl,
        });
        const importedText = importRes.data.text;
        const res = await api.post("/api/v1/jobs/analyze-text", {
          text: importedText,
          document_id: preDocId,
        });
        job = res.data as ScanJob;
      }

      setActiveJob(job);
      toast.add("info", "Scan started — feel free to navigate away.");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Analysis failed. Please try again.";
      setError(detail);
      toast.add("error", detail);
      clearActiveJob();
    } finally {
      setSubmitting(false);
    }
  };

  const handleNewScan = () => {
    clearActiveJob();
    setResult(null);
    setError("");
    setText("");
    setFile(null);
    setGoogleUrl("");
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = e.dataTransfer.files[0];
    if (dropped) {
      setFile(dropped);
      setMode("file");
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setMode("file");
    }
  };

  const loadSample = () => {
    setMode("text");
    setText(SAMPLE_TEXT);
  };

  const quotaLimit = typeof usage?.word_quota.limit === "number" ? usage.word_quota.limit : 0;
  const quotaUsed = usage?.word_quota.used ?? 0;
  const quotaRemaining = typeof usage?.word_quota.remaining === "number" ? usage.word_quota.remaining : -1;
  const topupRemaining = usage?.word_quota.topup_remaining ?? 0;
  const quotaPct = quotaLimit > 0 ? quotaUsed / quotaLimit : 0;
  const quotaTone = quotaPct >= 1 ? "danger" : quotaPct > 0.9 ? "danger" : quotaPct > 0.7 ? "warning" : "default";

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-accent/15 grid place-items-center">
            <Search className="w-5 h-5 text-accent" />
          </div>
          <h1 className="text-2xl font-bold">Analyze</h1>
        </div>
        <p className="text-sm text-muted ml-[52px]">
          <span className="inline-flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5" />
            5 agents
          </span>
          <span className="mx-2 text-muted/40">·</span>
          <span className="inline-flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            ~30 seconds
          </span>
          <span className="mx-2 text-muted/40">·</span>
          every finding is sourced
        </p>
      </div>

      {/* Usage overview */}
      {usage && (
        <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 bg-surface border border-border rounded-xl text-sm">
          <div className="flex items-center gap-2">
            <Badge
              variant={
                usage.plan_type === "premium"
                  ? "warning"
                  : usage.plan_type === "pro"
                    ? "accent"
                    : "default"
              }
            >
              {usage.plan_type.charAt(0).toUpperCase() + usage.plan_type.slice(1)}
            </Badge>
          </div>

          <div className="flex items-center gap-1.5 text-muted">
            <BarChart3 className="w-3.5 h-3.5" />
            <span>
              <span className="font-semibold text-txt">
                {usage.word_quota.used.toLocaleString()}
              </span>
              {" / "}
              {quotaLimit > 0
                ? `${quotaLimit.toLocaleString()} words`
                : "unlimited"}
            </span>
            {quotaLimit > 0 && (
                <div className="ml-2 w-24 h-1.5 bg-border rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.min(
                        quotaPct * 100,
                        100
                      )}%`,
                      backgroundColor:
                        quotaPct > 0.9
                          ? "var(--danger)"
                          : quotaPct > 0.7
                            ? "var(--warn)"
                            : "var(--accent)",
                    }}
                  />
                </div>
              )}
          </div>

          {quotaLimit > 0 && quotaPct > 0.7 && (
            <div className="flex items-center gap-1.5 text-xs">
              <AlertCircle className="w-3.5 h-3.5 text-warn" />
              <Badge variant={quotaTone === "danger" ? "danger" : "warning"}>
                {quotaRemaining === 0 ? "Quota exhausted" : `${quotaRemaining.toLocaleString()} words left`}
              </Badge>
              {topupRemaining > 0 && (
                <span className="text-muted">+ {topupRemaining.toLocaleString()} top-up words</span>
              )}
            </div>
          )}

          <div className="flex items-center gap-1.5 text-muted">
            <Clock className="w-3.5 h-3.5" />
            <span>
              <span className="font-semibold text-txt">{usage.used_today}</span>
              {" scans today"}
            </span>
          </div>

          <Link
            href={quotaLimit > 0 && quotaPct > 0.9 ? "/pricing" : "/dashboard/settings"}
            className="ml-auto text-xs text-accent-l hover:text-accent transition-colors"
          >
            {quotaLimit > 0 && quotaPct > 0.9 ? "Upgrade / top-up →" : "Settings →"}
          </Link>
        </div>
      )}

      {/* Unified input card */}
      <div className="bg-surface border border-border rounded-2xl overflow-hidden shadow-sm mb-8">
        {/* Tab strip */}
        <div className="flex items-center justify-between border-b border-border px-4 pt-3">
          <div className="flex gap-1">
            {(
              [
                { id: "text", label: "Paste Text", icon: FileText },
                { id: "file", label: "Upload File", icon: Upload },
                { id: "url", label: "Google Docs", icon: LinkIcon },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                onClick={() => setMode(tab.id)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                  mode === tab.id
                    ? "border-accent text-accent-l"
                    : "border-transparent text-muted hover:text-txt"
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
          {mode === "text" && !text && (
            <button
              onClick={loadSample}
              className="hidden sm:inline-flex items-center gap-1 text-xs font-medium text-accent-l hover:text-accent transition-colors pb-2"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Try sample
              <ArrowRight className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="p-5">
          {mode === "text" && (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste your text here to check for plagiarism and AI-generated content…"
              className="w-full h-56 bg-transparent border-0 text-txt placeholder:text-muted/50 focus:outline-none text-sm leading-relaxed resize-none"
            />
          )}

          {mode === "file" && (
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              className="border-2 border-dashed border-border rounded-xl p-10 text-center hover:border-accent/50 transition-colors"
            >
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <FileText className="w-8 h-8 text-accent" />
                  <div className="text-left">
                    <p className="text-sm font-medium">{file.name}</p>
                    <p className="text-xs text-muted">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <button
                    onClick={() => setFile(null)}
                    className="ml-4 text-muted hover:text-danger transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <>
                  <Upload className="w-10 h-10 text-muted mx-auto mb-3" />
                  <p className="text-sm text-muted mb-1">
                    Drag &amp; drop a file here, or click to browse
                  </p>
                  <p className="text-xs text-muted/60 mb-4">
                    Supports PDF, DOCX, TXT, PPTX (max 100MB)
                  </p>
                  <label className="inline-flex items-center px-4 py-2 bg-surface2 hover:bg-border text-txt rounded-xl text-sm font-medium cursor-pointer transition-colors border border-border">
                    Choose File
                    <input
                      type="file"
                      onChange={handleFileSelect}
                      accept=".pdf,.docx,.txt,.pptx"
                      className="hidden"
                    />
                  </label>
                </>
              )}
            </div>
          )}

          {mode === "url" && (
            <div className="py-4">
              <label className="block text-sm font-medium mb-2">
                Google Docs URL
              </label>
              <input
                type="url"
                value={googleUrl}
                onChange={(e) => setGoogleUrl(e.target.value)}
                placeholder="https://docs.google.com/document/d/..."
                className="w-full px-4 py-3 bg-bg border border-border rounded-xl text-txt placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
              />
              <p className="text-xs text-muted mt-2">
                Document must be shared as &quot;Anyone with the link can view&quot;.
              </p>
            </div>
          )}
        </div>

        {/* Footer: counter, agents, button */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 px-5 py-4 border-t border-border bg-bg/30">
          <div className="flex items-center gap-4 flex-wrap">
            {mode === "text" && (
              <span className="text-xs text-muted whitespace-nowrap">
                {wordCount(text).toLocaleString()} words ·{" "}
                {text.length.toLocaleString()} chars
              </span>
            )}
            <div className="hidden md:flex items-center gap-1.5 flex-wrap">
              {AGENTS.map((a) => (
                <span
                  key={a.name}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface2 border border-border text-[11px] font-medium text-muted"
                >
                  <a.icon className={`w-3 h-3 ${a.color}`} />
                  {a.name}
                </span>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {mode === "text" && text && (
              <button
                onClick={() => setText("")}
                className="text-xs text-muted hover:text-danger transition-colors px-2"
              >
                Clear
              </button>
            )}
            <Button
              onClick={handleAnalyze}
              loading={loading}
              size="lg"
              className="min-w-[140px]"
            >
              {loading ? "Analyzing…" : "Analyze"}
              {!loading && <ArrowRight className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-danger/10 border border-danger/20 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {/* Loading / progress */}
      {isRunning && <ScanProgressBar />}

      {/* Results */}
      {result && (
        <div className="mb-8">
          <div className="flex items-center justify-end mb-3">
            <button
              onClick={handleNewScan}
              className="text-xs font-medium text-accent-l hover:text-accent inline-flex items-center gap-1"
            >
              Start a new scan
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
          <Results result={result} />
        </div>
      )}

      {/* Recent analyses */}
      {!loading && !result && recent.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">
              Recent analyses
            </h2>
            <Link
              href="/dashboard/history"
              className="text-xs text-accent-l hover:text-accent inline-flex items-center gap-1"
            >
              View all
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {recent.map((s) => (
              <Link
                key={s.id}
                href="/dashboard/history"
                className="block bg-surface border border-border rounded-xl p-4 hover:border-accent/40 hover:shadow-md transition-all group"
              >
                <div className="flex items-start justify-between mb-3 gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate group-hover:text-accent-l transition-colors">
                      {s.filename || `Scan #${s.id}`}
                    </p>
                    <p className="text-xs text-muted mt-0.5">
                      {formatDate(s.created_at)}
                    </p>
                  </div>
                  <Badge variant={riskTone(s.risk_level)}>
                    {s.risk_level}
                  </Badge>
                </div>
                <div className="grid grid-cols-3 gap-2 pt-3 border-t border-border">
                  <div>
                    <p className="text-[10px] text-muted uppercase tracking-wide">
                      Score
                    </p>
                    <p className="text-sm font-semibold">
                      {(s.plagiarism_score ?? 0).toFixed(0)}%
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted uppercase tracking-wide">
                      Sources
                    </p>
                    <p className="text-sm font-semibold">{s.sources_count}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-muted uppercase tracking-wide">
                      Flagged
                    </p>
                    <p className="text-sm font-semibold">{s.flagged_count}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
