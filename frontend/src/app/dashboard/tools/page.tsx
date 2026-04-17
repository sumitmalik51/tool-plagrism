"use client";

import { useState, useRef } from "react";
import {
  GitCompare,
  Highlighter,
  Layers,
  PenLine,
  SpellCheck,
  BookOpen,
  Upload,
  Copy,
  Download,
  Check,
  X,
  FileText,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { scoreColor } from "@/lib/utils";
import { Button, Input, Textarea, Badge, Tabs } from "@/components/ui";
import Card from "@/components/ui/Card";

const TOOL_TABS = [
  { id: "compare", label: "Compare", icon: <GitCompare className="w-4 h-4" /> },
  { id: "highlight", label: "Highlight", icon: <Highlighter className="w-4 h-4" /> },
  { id: "batch", label: "Batch", icon: <Layers className="w-4 h-4" /> },
  { id: "rewrite", label: "Rewrite", icon: <PenLine className="w-4 h-4" /> },
  { id: "grammar", label: "Grammar", icon: <SpellCheck className="w-4 h-4" /> },
  { id: "readability", label: "Readability", icon: <BookOpen className="w-4 h-4" /> },
];

export default function ToolsPage() {
  const [activeTab, setActiveTab] = useState("compare");

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Tools</h1>
      <Tabs
        tabs={TOOL_TABS}
        active={activeTab}
        onChange={setActiveTab}
      />
      {activeTab === "compare" && <CompareTab />}
      {activeTab === "highlight" && <HighlightTab />}
      {activeTab === "batch" && <BatchTab />}
      {activeTab === "rewrite" && <RewriteTab />}
      {activeTab === "grammar" && <GrammarTab />}
      {activeTab === "readability" && <ReadabilityTab />}
    </div>
  );
}

/* ─── Compare ───────────────────────────────────────────── */

interface CompareResult {
  score_diff: {
    plagiarism_score: { a: number; b: number; change: number };
    confidence_score: { a: number; b: number; change: number };
    risk_level: { a: string; b: string };
    sources_count: { a: number; b: number; change: number };
    flagged_count: { a: number; b: number; change: number };
  };
  new_sources: { url: string; title: string; similarity: number }[];
  removed_sources: { url: string; title: string; similarity: number }[];
}

function CompareTab() {
  const toast = useToastStore();
  const [idA, setIdA] = useState("");
  const [idB, setIdB] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompareResult | null>(null);

  const compare = async () => {
    if (!idA.trim() || !idB.trim()) {
      toast.add("warning", "Enter both Document IDs.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post("/api/v1/compare-scans", {
        document_id_a: idA.trim(),
        document_id_b: idB.trim(),
      });
      setResult(res.data);
    } catch {
      toast.add("error", "Failed to compare scans.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Compare two scans to see how scores and sources changed.
        </p>
        <div className="grid sm:grid-cols-2 gap-4 mb-4">
          <Input
            label="Document ID A"
            placeholder="Paste first document ID"
            value={idA}
            onChange={(e) => setIdA(e.target.value)}
          />
          <Input
            label="Document ID B"
            placeholder="Paste second document ID"
            value={idB}
            onChange={(e) => setIdB(e.target.value)}
          />
        </div>
        <Button onClick={compare} loading={loading}>
          <GitCompare className="w-4 h-4 mr-1" /> Compare
        </Button>
      </Card>

      {result && (
        <Card>
          <h3 className="text-lg font-semibold mb-4">Comparison Results</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
            <DiffCard
              label="Plagiarism"
              a={result.score_diff.plagiarism_score.a}
              b={result.score_diff.plagiarism_score.b}
              change={result.score_diff.plagiarism_score.change}
              suffix="%"
            />
            <DiffCard
              label="Sources"
              a={result.score_diff.sources_count.a}
              b={result.score_diff.sources_count.b}
              change={result.score_diff.sources_count.change}
            />
            <DiffCard
              label="Flagged"
              a={result.score_diff.flagged_count.a}
              b={result.score_diff.flagged_count.b}
              change={result.score_diff.flagged_count.change}
            />
          </div>
          {result.new_sources.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-semibold text-danger mb-2">
                New Sources (+{result.new_sources.length})
              </h4>
              {result.new_sources.map((s, i) => (
                <p key={i} className="text-xs text-muted">
                  {s.title || s.url} — {(s.similarity * 100).toFixed(1)}%
                </p>
              ))}
            </div>
          )}
          {result.removed_sources.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-ok mb-2">
                Resolved Sources (-{result.removed_sources.length})
              </h4>
              {result.removed_sources.map((s, i) => (
                <p key={i} className="text-xs text-muted">
                  {s.title || s.url} — {(s.similarity * 100).toFixed(1)}%
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function DiffCard({
  label,
  a,
  b,
  change,
  suffix = "",
}: {
  label: string;
  a: number;
  b: number;
  change: number;
  suffix?: string;
}) {
  const color =
    change > 0 ? "text-danger" : change < 0 ? "text-ok" : "text-muted";
  return (
    <div className="bg-bg rounded-xl p-3 text-center">
      <p className="text-xs text-muted mb-1">{label}</p>
      <div className="flex items-center justify-center gap-2 text-sm">
        <span>
          {a.toFixed(1)}
          {suffix}
        </span>
        <span className="text-muted">→</span>
        <span>
          {b.toFixed(1)}
          {suffix}
        </span>
      </div>
      <p className={`text-xs font-semibold mt-1 ${color}`}>
        {change > 0 ? "+" : ""}
        {change.toFixed(1)}
        {suffix}
      </p>
    </div>
  );
}

/* ─── Highlight ─────────────────────────────────────────── */

function HighlightTab() {
  const toast = useToastStore();
  const [shareId, setShareId] = useState("");
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<{
    plagiarism_score: number;
    risk_level: string;
    report: {
      flagged_passages: { text: string; similarity_score: number; source: string }[];
      detected_sources: { title: string; url: string; similarity: number; source_type: string; matched_words: number }[];
    };
  } | null>(null);

  const load = async () => {
    if (!shareId.trim()) {
      toast.add("warning", "Enter a Share ID.");
      return;
    }
    setLoading(true);
    setReport(null);
    try {
      const res = await api.get(`/api/v1/shared/${shareId.trim()}`);
      setReport(res.data);
    } catch {
      toast.add("error", "Failed to load shared report.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Load a shared report to view highlighted passages with source
          attribution.
        </p>
        <div className="flex gap-3">
          <div className="flex-1">
            <Input
              placeholder="Enter Share ID"
              value={shareId}
              onChange={(e) => setShareId(e.target.value)}
            />
          </div>
          <Button onClick={load} loading={loading}>
            <Highlighter className="w-4 h-4 mr-1" /> Load
          </Button>
        </div>
      </Card>

      {report && (
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-3">
            <Card>
              <div className="flex items-center gap-3 mb-4">
                <span
                  className={`text-xl font-bold ${scoreColor(
                    report.plagiarism_score
                  )}`}
                >
                  {report.plagiarism_score.toFixed(1)}%
                </span>
                <Badge
                  variant={
                    report.risk_level === "LOW"
                      ? "success"
                      : report.risk_level === "MEDIUM"
                      ? "warning"
                      : "danger"
                  }
                >
                  {report.risk_level}
                </Badge>
              </div>
              <h3 className="text-sm font-semibold text-muted mb-3">
                Flagged Passages
              </h3>
              <div className="space-y-2">
                {report.report.flagged_passages.map((p, i) => (
                  <div
                    key={i}
                    className="p-3 bg-danger/5 border-l-4 border-danger/30 rounded-r-lg"
                  >
                    <p className="text-sm text-txt/80">{p.text}</p>
                    <p className="text-xs text-muted mt-1">
                      {(p.similarity_score * 100).toFixed(1)}% — {p.source}
                    </p>
                  </div>
                ))}
                {report.report.flagged_passages.length === 0 && (
                  <p className="text-sm text-muted">No flagged passages.</p>
                )}
              </div>
            </Card>
          </div>
          <div>
            <Card>
              <h3 className="text-sm font-semibold text-muted mb-3">
                Sources ({report.report.detected_sources.length})
              </h3>
              <div className="space-y-2">
                {report.report.detected_sources.map((s, i) => (
                  <div key={i} className="p-2 bg-bg rounded-lg">
                    <p className="text-xs font-medium truncate">
                      {s.title || s.url}
                    </p>
                    <p className="text-xs text-muted">
                      {(s.similarity * 100).toFixed(1)}% — {s.matched_words}{" "}
                      words
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Batch ─────────────────────────────────────────────── */

interface BatchResult {
  total_files: number;
  completed: number;
  failed: number;
  results: {
    filename: string;
    document_id: string;
    plagiarism_score: number;
    risk_level: string;
    source_count: number;
  }[];
  errors: { filename: string; error: string }[];
}

function BatchTab() {
  const toast = useToastStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);

  const handleFiles = (selected: FileList | null) => {
    if (!selected) return;
    setFiles(Array.from(selected));
    setResult(null);
  };

  const analyze = async () => {
    if (files.length === 0) {
      toast.add("warning", "Select at least one file.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const res = await api.post("/api/v1/analyze-batch", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
      toast.add("success", `Analyzed ${res.data.completed} of ${res.data.total_files} files.`);
    } catch {
      toast.add("error", "Batch analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Upload multiple files for batch plagiarism analysis.
        </p>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.tex,.pptx"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <div
          onClick={() => fileRef.current?.click()}
          className="border-2 border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-accent/50 transition-colors"
        >
          <Upload className="w-8 h-8 mx-auto text-muted mb-2" />
          <p className="text-sm text-muted">
            Click to select files (PDF, DOCX, TXT, TeX, PPTX)
          </p>
          {files.length > 0 && (
            <p className="text-sm text-accent mt-2">
              {files.length} file{files.length > 1 ? "s" : ""} selected
            </p>
          )}
        </div>
        {files.length > 0 && (
          <div className="mt-4 space-y-1">
            {files.map((f, i) => (
              <div
                key={i}
                className="flex items-center gap-2 text-xs text-muted"
              >
                <FileText className="w-3 h-3" /> {f.name}
              </div>
            ))}
          </div>
        )}
        <Button onClick={analyze} loading={loading} className="mt-4">
          <Layers className="w-4 h-4 mr-1" /> Analyze Batch
        </Button>
      </Card>

      {result && (
        <Card>
          <div className="flex items-center gap-4 mb-4">
            <Badge variant="success">{result.completed} completed</Badge>
            {result.failed > 0 && (
              <Badge variant="danger">{result.failed} failed</Badge>
            )}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="py-2 px-2">Filename</th>
                <th className="py-2 px-2">Score</th>
                <th className="py-2 px-2">Risk</th>
                <th className="py-2 px-2">Sources</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((r, i) => (
                <tr key={i} className="border-b border-border/30">
                  <td className="py-2 px-2 truncate max-w-[200px]">
                    {r.filename}
                  </td>
                  <td
                    className={`py-2 px-2 font-semibold ${scoreColor(
                      r.plagiarism_score
                    )}`}
                  >
                    {r.plagiarism_score.toFixed(1)}%
                  </td>
                  <td className="py-2 px-2">
                    <Badge
                      variant={
                        r.risk_level === "LOW"
                          ? "success"
                          : r.risk_level === "MEDIUM"
                          ? "warning"
                          : "danger"
                      }
                    >
                      {r.risk_level}
                    </Badge>
                  </td>
                  <td className="py-2 px-2 text-muted">{r.source_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.errors.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-semibold text-danger mb-2">
                Errors
              </h4>
              {result.errors.map((e, i) => (
                <p key={i} className="text-xs text-muted">
                  <X className="w-3 h-3 inline text-danger mr-1" />
                  {e.filename}: {e.error}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/* ─── Rewrite ───────────────────────────────────────────── */

const REWRITE_MODES = [
  "paraphrase",
  "simplify",
  "expand",
  "formal",
  "casual",
  "academic",
  "humanize",
] as const;
const REWRITE_TONES = [
  "neutral",
  "friendly",
  "professional",
  "confident",
  "persuasive",
] as const;
const REWRITE_STRENGTHS = ["low", "medium", "high"] as const;

function RewriteTab() {
  const toast = useToastStore();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<string>("paraphrase");
  const [tone, setTone] = useState<string>("neutral");
  const [strength, setStrength] = useState<string>("medium");
  const [loading, setLoading] = useState(false);
  const [variations, setVariations] = useState<string[]>([]);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const rewrite = async () => {
    if (!text.trim()) {
      toast.add("warning", "Enter text to rewrite.");
      return;
    }
    setLoading(true);
    setVariations([]);
    try {
      const res = await api.post("/api/v1/rewrite/general", {
        text: text.trim(),
        mode,
        tone,
        strength,
      });
      setVariations(res.data.variations || []);
    } catch {
      toast.add("error", "Rewrite failed.");
    } finally {
      setLoading(false);
    }
  };

  const copyVariation = (v: string, idx: number) => {
    navigator.clipboard.writeText(v);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const exportDocx = async (variant: string) => {
    try {
      const res = await api.post(
        "/api/v1/rewrite/export-docx",
        { original: text, rewritten: variant, title: "Rewritten Document", show_changes: true },
        { responseType: "blob" }
      );
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "rewritten.docx";
      a.click();
      URL.revokeObjectURL(url);
      toast.add("success", "DOCX exported!");
    } catch {
      toast.add("error", "DOCX export failed.");
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <Textarea
          label="Text to Rewrite"
          rows={6}
          placeholder="Paste your text here…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="grid sm:grid-cols-3 gap-3 mt-4">
          <SelectField label="Mode" value={mode} onChange={setMode} options={REWRITE_MODES} />
          <SelectField label="Tone" value={tone} onChange={setTone} options={REWRITE_TONES} />
          <SelectField label="Strength" value={strength} onChange={setStrength} options={REWRITE_STRENGTHS} />
        </div>
        <Button onClick={rewrite} loading={loading} className="mt-4">
          <PenLine className="w-4 h-4 mr-1" /> Rewrite
        </Button>
      </Card>

      {variations.length > 0 && (
        <div className="grid lg:grid-cols-3 gap-4">
          {variations.map((v, i) => (
            <Card key={i}>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-accent">
                  Variation {i + 1}
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => copyVariation(v, i)}
                    className="p-1 rounded hover:bg-surface2 text-muted hover:text-txt transition-colors"
                    title="Copy"
                  >
                    {copiedIdx === i ? (
                      <Check className="w-3.5 h-3.5 text-ok" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => exportDocx(v)}
                    className="p-1 rounded hover:bg-surface2 text-muted hover:text-txt transition-colors"
                    title="Export DOCX"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <p className="text-sm text-txt/80 leading-relaxed whitespace-pre-wrap">
                {v}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── Grammar ───────────────────────────────────────────── */

interface GrammarError {
  type: string;
  offset: number;
  length: number;
  message: string;
  suggestions: string[];
  confidence: number;
}

function GrammarTab() {
  const toast = useToastStore();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<GrammarError[]>([]);
  const [summary, setSummary] = useState<{
    total_errors: number;
    by_type: Record<string, number>;
  } | null>(null);

  const check = async () => {
    if (!text.trim()) {
      toast.add("warning", "Enter text to check.");
      return;
    }
    setLoading(true);
    setErrors([]);
    setSummary(null);
    try {
      const res = await api.post("/api/v1/grammar/check", { text: text.trim() });
      setErrors(res.data.errors || []);
      setSummary(res.data.summary || null);
    } catch {
      toast.add("error", "Grammar check failed.");
    } finally {
      setLoading(false);
    }
  };

  const typeColor: Record<string, string> = {
    spelling: "text-danger",
    grammar: "text-warn",
    style: "text-accent-l",
    punctuation: "text-muted",
  };

  return (
    <div className="space-y-4">
      <Card>
        <Textarea
          label="Text to Check"
          rows={6}
          placeholder="Paste your text here…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button onClick={check} loading={loading} className="mt-4">
          <SpellCheck className="w-4 h-4 mr-1" /> Check Grammar
        </Button>
      </Card>

      {summary && (
        <Card>
          <div className="flex items-center gap-4 mb-4 flex-wrap">
            <span className="text-sm font-semibold">
              {summary.total_errors} error
              {summary.total_errors !== 1 ? "s" : ""} found
            </span>
            {Object.entries(summary.by_type).map(([type, count]) => (
              <Badge key={type} variant="default">
                {type}: {count}
              </Badge>
            ))}
          </div>
          <div className="space-y-3">
            {errors.map((err, i) => (
              <div key={i} className="p-3 bg-bg rounded-xl">
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="default" className={typeColor[err.type] || ""}>
                    {err.type}
                  </Badge>
                  <span className="text-xs text-muted">
                    offset {err.offset}, length {err.length}
                  </span>
                </div>
                <p className="text-sm mb-1">{err.message}</p>
                {err.suggestions.length > 0 && (
                  <p className="text-xs text-ok">
                    Suggestions: {err.suggestions.join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ─── Readability ───────────────────────────────────────── */

interface ReadabilityResult {
  word_count: number;
  sentence_count: number;
  paragraph_count: number;
  scores: {
    flesch_kincaid_grade: number;
    flesch_reading_ease: number;
    gunning_fog_index: number;
    coleman_liau_index: number;
    smog_index: number;
  };
  grade_level: number;
  reading_time_minutes: number;
  reading_level: string;
  improvement_tips: string[];
}

function ReadabilityTab() {
  const toast = useToastStore();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReadabilityResult | null>(null);

  const analyze = async () => {
    if (!text.trim()) {
      toast.add("warning", "Enter text to analyze.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post("/api/v1/readability", { text: text.trim() });
      setResult(res.data);
    } catch {
      toast.add("error", "Readability analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <Textarea
          label="Text to Analyze"
          rows={6}
          placeholder="Paste your text here…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button onClick={analyze} loading={loading} className="mt-4">
          <BookOpen className="w-4 h-4 mr-1" /> Analyze
        </Button>
      </Card>

      {result && (
        <div className="space-y-4">
          {/* Quick stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Words" value={result.word_count} />
            <StatCard label="Sentences" value={result.sentence_count} />
            <StatCard
              label="Reading Time"
              value={`${result.reading_time_minutes.toFixed(1)} min`}
            />
            <StatCard label="Level" value={result.reading_level} />
          </div>

          {/* Scores */}
          <Card>
            <h3 className="text-sm font-semibold text-muted mb-4">
              Readability Scores
            </h3>
            <div className="grid sm:grid-cols-2 gap-4">
              <ScoreRow
                label="Flesch Reading Ease"
                value={result.scores.flesch_reading_ease}
                max={100}
              />
              <ScoreRow
                label="Flesch-Kincaid Grade"
                value={result.scores.flesch_kincaid_grade}
                max={20}
              />
              <ScoreRow
                label="Gunning Fog Index"
                value={result.scores.gunning_fog_index}
                max={20}
              />
              <ScoreRow
                label="Coleman-Liau Index"
                value={result.scores.coleman_liau_index}
                max={20}
              />
              <ScoreRow
                label="SMOG Index"
                value={result.scores.smog_index}
                max={20}
              />
              <ScoreRow
                label="Grade Level"
                value={result.grade_level}
                max={20}
              />
            </div>
          </Card>

          {/* Tips */}
          {result.improvement_tips.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold text-muted mb-3">
                Improvement Tips
              </h3>
              <ul className="space-y-2">
                {result.improvement_tips.map((tip, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-txt/80">
                    <Check className="w-4 h-4 text-ok shrink-0 mt-0.5" />
                    {tip}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Shared sub-components ──────────────────────────────── */

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-muted mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-border rounded-xl px-3 py-2 text-sm text-txt focus:outline-none focus:ring-2 focus:ring-accent/50"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o.charAt(0).toUpperCase() + o.slice(1)}
          </option>
        ))}
      </select>
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="bg-surface border border-border rounded-xl p-3 text-center">
      <p className="text-xs text-muted">{label}</p>
      <p className="text-lg font-bold mt-1">{value}</p>
    </div>
  );
}

function ScoreRow({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-muted">{label}</span>
        <span className="font-semibold">{value.toFixed(1)}</span>
      </div>
      <div className="h-2 bg-bg rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
