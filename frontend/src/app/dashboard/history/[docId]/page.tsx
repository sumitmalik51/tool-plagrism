"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Download,
  Clock,
  FileText,
  ExternalLink,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { formatDate, scoreColor } from "@/lib/utils";

function riskVariant(risk: string): "success" | "warning" | "danger" {
  switch (risk.toUpperCase()) {
    case "LOW": return "success";
    case "MEDIUM": return "warning";
    default: return "danger";
  }
}
import { Button, Badge, Spinner } from "@/components/ui";
import Card from "@/components/ui/Card";
import Results from "@/components/Results";
import type { AnalysisResult } from "@/lib/types";

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
    match_groups?: { category: string; icon: string; count: number; percentage: number }[];
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

export default function ScanDetailPage() {
  const { docId } = useParams<{ docId: string }>();
  const router = useRouter();
  const toast = useToastStore();

  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!docId) return;
    const load = async () => {
      setLoading(true);
      try {
        const [scanRes, revRes] = await Promise.all([
          api.get(`/api/v1/auth/scans/${docId}`),
          api.get(`/api/v1/auth/scans/${docId}/revisions`).catch(() => ({
            data: { revisions: [] },
          })),
        ]);
        setScan(scanRes.data);
        setRevisions(revRes.data.revisions || []);
      } catch {
        toast.add("error", "Failed to load scan details.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [docId, toast]);

  const downloadPdf = async () => {
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
  };

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!scan) {
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
  }

  const report = scan.report_json;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <button
            onClick={() => router.push("/dashboard/history")}
            className="flex items-center gap-1 text-sm text-muted hover:text-txt transition-colors mb-2"
          >
            <ArrowLeft className="w-4 h-4" /> Back to History
          </button>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            <FileText className="w-6 h-6 text-accent" />
            {scan.filename || scan.document_id.slice(0, 16) + "…"}
          </h1>
          <p className="text-sm text-muted mt-1">
            Scanned on {formatDate(scan.created_at)}
          </p>
        </div>
        <Button variant="secondary" onClick={downloadPdf}>
          <Download className="w-4 h-4 mr-1" />
          Download PDF
        </Button>
      </div>

      {/* Explanation */}
      {report.explanation && (
        <Card>
          <p className="text-sm text-txt/80 leading-relaxed">
            {report.explanation}
          </p>
        </Card>
      )}

      {/* Match groups */}
      {report.match_groups && report.match_groups.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {report.match_groups.map((g, i) => (
            <div
              key={i}
              className="bg-surface border border-border rounded-xl p-3 text-center"
            >
              <span className="text-lg mb-1 block">{g.icon}</span>
              <p className="text-xs text-muted">{g.category}</p>
              <p className="text-lg font-bold">
                {g.percentage.toFixed(1)}%{" "}
                <span className="text-xs text-muted font-normal">
                  ({g.count})
                </span>
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Full results reuse */}
      <Results result={report} />

      {/* Original text (collapsible) */}
      {report.original_text && (
        <details className="bg-surface border border-border rounded-2xl overflow-hidden">
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

      {/* Revisions */}
      {revisions.length > 1 && (
        <Card>
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
                className={`flex items-center justify-between p-3 rounded-xl cursor-pointer transition-colors ${
                  rev.document_id === docId
                    ? "bg-accent/10 border border-accent/30"
                    : "bg-bg hover:bg-surface2"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted">
                    {formatDate(rev.created_at)}
                  </span>
                  <span
                    className={`text-sm font-semibold ${scoreColor(
                      rev.plagiarism_score
                    )}`}
                  >
                    {rev.plagiarism_score.toFixed(1)}%
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
        </Card>
      )}

      {/* Sources with links */}
      {report.detected_sources.length > 0 && (
        <Card>
          <h3 className="text-lg font-semibold mb-4">
            Source Details
          </h3>
          <div className="space-y-3">
            {report.detected_sources.map((src, i) => (
              <div key={i} className="p-4 bg-bg rounded-xl">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-bold text-muted">
                    #{(src as unknown as { source_number?: number }).source_number ?? i + 1}
                  </span>
                  <Badge variant="default">{src.source_type}</Badge>
                  <span
                    className={`text-sm font-semibold ${scoreColor(
                      src.similarity * 100
                    )}`}
                  >
                    {(src.similarity * 100).toFixed(1)}%
                  </span>
                </div>
                <p className="text-sm font-medium mb-1">
                  {src.title || "Untitled"}
                </p>
                {src.url && (
                  <a
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-accent-l hover:text-accent flex items-center gap-1"
                  >
                    <ExternalLink className="w-3 h-3" />
                    {src.url.length > 80
                      ? src.url.slice(0, 80) + "…"
                      : src.url}
                  </a>
                )}
                <p className="text-xs text-muted mt-1">
                  {src.matched_words} words matched across {src.text_blocks}{" "}
                  blocks
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
