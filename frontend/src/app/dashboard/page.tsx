"use client";

import { useState, useCallback } from "react";
import {
  Search,
  Upload,
  FileText,
  Link as LinkIcon,
  X,
  AlertCircle,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import Results from "@/components/Results";
import type { AnalysisResult } from "@/lib/types";
import { wordCount } from "@/lib/utils";

type InputMode = "text" | "file" | "url";

export default function AnalyzerPage() {
  const [mode, setMode] = useState<InputMode>("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [googleUrl, setGoogleUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");

  const toast = useToastStore();

  const handleAnalyze = async () => {
    setError("");
    setResult(null);
    setLoading(true);

    try {
      let data: AnalysisResult;

      if (mode === "text") {
        if (!text.trim() || wordCount(text) < 3) {
          setError("Please enter at least a few words to analyze.");
          setLoading(false);
          return;
        }
        const res = await api.post("/api/v1/analyze-agent", { text });
        data = res.data;
      } else if (mode === "file") {
        if (!file) {
          setError("Please select a file to upload.");
          setLoading(false);
          return;
        }
        const formData = new FormData();
        formData.append("file", file);
        const res = await api.post("/api/v1/analyze", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        data = res.data;
      } else {
        if (!googleUrl.trim()) {
          setError("Please enter a Google Docs URL.");
          setLoading(false);
          return;
        }
        const importRes = await api.post("/api/v1/import-google-doc", {
          url: googleUrl,
        });
        const importedText = importRes.data.text;
        const res = await api.post("/api/v1/analyze-agent", {
          text: importedText,
        });
        data = res.data;
      }

      setResult(data);
      toast.add("success", "Analysis complete!");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Analysis failed. Please try again.";
      setError(detail);
      toast.add("error", detail);
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) {
        setFile(droppedFile);
        setMode("file");
      }
    },
    []
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setMode("file");
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Search className="w-6 h-6 text-accent" />
        <h1 className="text-2xl font-bold">Analyze</h1>
      </div>

      {/* Input mode tabs */}
      <div className="flex gap-1 bg-surface rounded-xl p-1 border border-border mb-6 w-fit">
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
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === tab.id
                ? "bg-accent text-white shadow-sm"
                : "text-muted hover:text-txt hover:bg-surface2"
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Input area */}
      <div className="bg-surface border border-border rounded-2xl p-6 mb-6">
        {mode === "text" && (
          <div>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste your text here to check for plagiarism…"
              className="w-full h-64 bg-transparent border-0 text-txt placeholder:text-muted/50 focus:outline-none resize-y text-sm leading-relaxed"
            />
            <div className="flex items-center justify-between pt-3 border-t border-border">
              <span className="text-xs text-muted">
                {wordCount(text).toLocaleString()} words •{" "}
                {text.length.toLocaleString()} chars
              </span>
              {text && (
                <button
                  onClick={() => setText("")}
                  className="text-xs text-muted hover:text-danger transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
        )}

        {mode === "file" && (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            className="border-2 border-dashed border-border rounded-xl p-12 text-center hover:border-accent/50 transition-colors"
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
                <p className="text-sm text-muted mb-2">
                  Drag &amp; drop a file here, or click to browse
                </p>
                <p className="text-xs text-muted/60">
                  Supports PDF, DOCX, TXT, PPTX (max 100MB)
                </p>
                <label className="mt-4 inline-flex items-center px-4 py-2 bg-surface2 hover:bg-border text-txt rounded-xl text-sm font-medium cursor-pointer transition-colors border border-border">
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
          <div>
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
              Document must be shared as &quot;Anyone with the link can view&quot;
            </p>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 bg-danger/10 border border-danger/20 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {/* Analyze button */}
      <div className="mb-8">
        <Button
          onClick={handleAnalyze}
          loading={loading}
          size="lg"
          className="w-full sm:w-auto"
          disabled={
            loading ||
            (mode === "text" && !text.trim()) ||
            (mode === "file" && !file) ||
            (mode === "url" && !googleUrl.trim())
          }
        >
          {loading ? "Analyzing…" : "Analyze"}
        </Button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="bg-surface border border-border rounded-2xl p-12 text-center">
          <Spinner size="lg" className="mx-auto mb-4" />
          <p className="text-muted">
            Scanning against 250M+ scholarly sources…
          </p>
          <p className="text-xs text-muted/60 mt-1">This may take 15–30 seconds</p>
        </div>
      )}

      {/* Results */}
      {result && !loading && <Results result={result} />}
    </div>
  );
}
