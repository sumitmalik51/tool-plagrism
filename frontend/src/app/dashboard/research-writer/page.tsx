"use client";

import { useEffect, useState, useRef } from "react";
import {
  Upload,
  FileImage,
  Sparkles,
  Search,
  Expand,
  Wand2,
  Image as ImageIcon,
  Copy,
  Check,
  BookOpen,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { Button, Textarea, Badge, Tabs, Input } from "@/components/ui";
import Card from "@/components/ui/Card";

const RW_TABS = [
  { id: "generate", label: "Generate", icon: <Sparkles className="w-4 h-4" /> },
  { id: "check", label: "Check", icon: <Search className="w-4 h-4" /> },
  { id: "expand", label: "Expand", icon: <Expand className="w-4 h-4" /> },
  { id: "improve", label: "Improve", icon: <Wand2 className="w-4 h-4" /> },
  { id: "caption", label: "Caption", icon: <ImageIcon className="w-4 h-4" /> },
  { id: "sources", label: "Sources", icon: <BookOpen className="w-4 h-4" /> },
];

interface Status {
  plan: string;
  remaining: Record<string, number>;
  limits: Record<string, number>;
  credits: number;
  is_free: boolean;
}

export default function ResearchWriterPage() {
  const toast = useToastStore();
  const [activeTab, setActiveTab] = useState("generate");
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    api
      .get("/api/v1/research-writer/status")
      .then((r) => setStatus(r.data))
      .catch(() => toast.add("error", "Failed to load status."));
  }, [toast]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Research Writer</h1>
        {status && (
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="accent">{status.plan.toUpperCase()}</Badge>
            <span className="text-xs text-muted">
              Credits: {status.credits}
            </span>
          </div>
        )}
      </div>

      {/* Status bar */}
      {status && (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {Object.entries(status.remaining).map(([key, remaining]) => {
            const limit = status.limits[key] ?? 0;
            const label = key.replace("rw_", "");
            return (
              <div
                key={key}
                className="bg-surface border border-border rounded-xl px-3 py-2 text-center min-w-[80px]"
              >
                <p className="text-[10px] text-muted capitalize">{label}</p>
                <p className="text-sm font-bold">
                  {remaining}
                  <span className="text-muted font-normal">/{limit}</span>
                </p>
              </div>
            );
          })}
        </div>
      )}

      <Tabs tabs={RW_TABS} active={activeTab} onChange={setActiveTab} />

      {activeTab === "generate" && <GenerateTab />}
      {activeTab === "check" && <CheckTab />}
      {activeTab === "expand" && <ExpandTab />}
      {activeTab === "improve" && <ImproveTab />}
      {activeTab === "caption" && <CaptionTab />}
      {activeTab === "sources" && <SourcesTab />}
    </div>
  );
}

/* ─── Generate ──────────────────────────────────────────── */

function GenerateTab() {
  const toast = useToastStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [explanation, setExplanation] = useState("");
  const [sectionType, setSectionType] = useState("results");
  const [citationStyle, setCitationStyle] = useState("apa");
  const [tone, setTone] = useState("academic");
  const [level, setLevel] = useState("undergraduate");
  const [researchTopic, setResearchTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    paragraph: string;
    figure_caption?: string;
    figure_description?: string;
    key_findings?: string[];
    graph_type?: string;
    suggested_sources?: { title: string; formatted_citation: string; source: string }[];
    session_id?: string;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    if (!explanation.trim() || explanation.trim().length < 20) {
      toast.add("warning", "Explanation must be at least 20 characters.");
      return;
    }
    if (!imageFile && !imageUrl.trim()) {
      toast.add("warning", "Provide an image (file or URL).");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("explanation", explanation.trim());
      fd.append("section_type", sectionType);
      fd.append("citation_style", citationStyle);
      fd.append("tone", tone);
      fd.append("level", level);
      if (researchTopic.trim()) fd.append("research_topic", researchTopic.trim());
      if (imageFile) {
        fd.append("image", imageFile);
      } else if (imageUrl.trim()) {
        fd.append("image_url", imageUrl.trim());
      }
      const res = await api.post("/api/v1/research-writer/generate", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
    } catch {
      toast.add("error", "Generation failed.");
    } finally {
      setLoading(false);
    }
  };

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Upload a graph/chart image and describe it to generate an academic paragraph.
        </p>

        {/* Image upload */}
        <div className="grid sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-muted mb-1">
              Image File
            </label>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                setImageFile(e.target.files?.[0] || null);
                setImageUrl("");
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full border-2 border-dashed border-border rounded-xl p-4 text-center hover:border-accent/50 transition-colors"
            >
              <FileImage className="w-6 h-6 mx-auto text-muted mb-1" />
              <p className="text-xs text-muted">
                {imageFile ? imageFile.name : "Click to upload image"}
              </p>
            </button>
          </div>
          <div>
            <Input
              label="Or Image URL"
              placeholder="https://example.com/chart.png"
              value={imageUrl}
              onChange={(e) => {
                setImageUrl(e.target.value);
                setImageFile(null);
              }}
            />
          </div>
        </div>

        <Textarea
          label="Explanation (describe the graph)"
          rows={4}
          placeholder="Describe what the graph shows, including trends, variables, and key observations…"
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
        />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          <SelectField
            label="Section"
            value={sectionType}
            onChange={setSectionType}
            options={["results", "discussion", "methodology", "analysis"]}
          />
          <SelectField
            label="Citation"
            value={citationStyle}
            onChange={setCitationStyle}
            options={["apa", "mla", "chicago"]}
          />
          <SelectField
            label="Tone"
            value={tone}
            onChange={setTone}
            options={["academic", "professional"]}
          />
          <SelectField
            label="Level"
            value={level}
            onChange={setLevel}
            options={["undergraduate", "masters", "phd"]}
          />
        </div>

        <Input
          label="Research Topic (optional)"
          placeholder="e.g., Machine learning in healthcare"
          value={researchTopic}
          onChange={(e) => setResearchTopic(e.target.value)}
          className="mt-4"
        />

        <Button onClick={generate} loading={loading} className="mt-4">
          <Sparkles className="w-4 h-4 mr-1" /> Generate
        </Button>
      </Card>

      {result && (
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold">Generated Paragraph</h3>
              <button
                onClick={() => copyText(result.paragraph as string)}
                className="p-2 rounded-lg hover:bg-surface2 text-muted hover:text-txt transition-colors"
              >
                {copied ? (
                  <Check className="w-4 h-4 text-ok" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            </div>
            <p className="text-sm text-txt/80 whitespace-pre-wrap leading-relaxed">
              {result.paragraph}
            </p>
            <div className="flex gap-3 mt-4 flex-wrap">
              {result.figure_caption && (
                <Badge variant="default">
                  Caption: {result.figure_caption}
                </Badge>
              )}
              {result.graph_type && (
                <Badge variant="accent">{result.graph_type}</Badge>
              )}
            </div>
          </Card>

          {result.key_findings && result.key_findings.length > 0 && (
            <Card>
              <h4 className="text-sm font-semibold text-muted mb-2">
                Key Findings
              </h4>
              <ul className="space-y-1">
                {result.key_findings.map((f, i) => (
                  <li key={i} className="text-sm text-txt/80 flex items-start gap-2">
                    <Check className="w-4 h-4 text-ok shrink-0 mt-0.5" />
                    {f}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {result.suggested_sources && result.suggested_sources.length > 0 && (
            <Card>
              <h4 className="text-sm font-semibold text-muted mb-2">
                Suggested Sources
              </h4>
              <div className="space-y-2">
                {result.suggested_sources.map(
                  (s, i) => (
                    <div key={i} className="p-2 bg-bg rounded-lg">
                      <p className="text-xs text-txt/70">
                        {s.formatted_citation}
                      </p>
                      <Badge variant="default" className="mt-1">
                        {s.source}
                      </Badge>
                    </div>
                  )
                )}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Check ─────────────────────────────────────────────── */

function CheckTab() {
  const toast = useToastStore();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    is_original: boolean;
    similarity_score: number;
    verdict: string;
    web_matches: { url: string; title: string; similarity: number }[];
    internal_matches: number;
  } | null>(null);

  const check = async () => {
    if (text.trim().length < 20) {
      toast.add("warning", "Text must be at least 20 characters.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post("/api/v1/research-writer/check", {
        text: text.trim(),
      });
      setResult(res.data);
    } catch {
      toast.add("error", "Check failed.");
    } finally {
      setLoading(false);
    }
  };

  const verdictColor: Record<string, string> = {
    original: "text-ok",
    needs_review: "text-warn",
    likely_plagiarized: "text-danger",
  };

  return (
    <div className="space-y-4">
      <Card>
        <Textarea
          label="Text to Check"
          rows={6}
          placeholder="Paste your generated text here (min 20 chars)…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button onClick={check} loading={loading} className="mt-4">
          <Search className="w-4 h-4 mr-1" /> Check
        </Button>
      </Card>

      {result && (
        <Card>
          <div className="flex items-center gap-4 mb-4 flex-wrap">
            <span
              className={`text-xl font-bold ${
                verdictColor[result.verdict] || "text-txt"
              }`}
            >
              {(result.similarity_score * 100).toFixed(1)}% similar
            </span>
            <Badge
              variant={
                result.verdict === "original"
                  ? "success"
                  : result.verdict === "needs_review"
                  ? "warning"
                  : "danger"
              }
            >
              {result.verdict.replace("_", " ").toUpperCase()}
            </Badge>
          </div>
          {result.web_matches.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-muted mb-2">
                Web Matches
              </h4>
              {result.web_matches.map((m, i) => (
                <div key={i} className="text-xs text-muted mb-1">
                  {m.title || m.url} — {(m.similarity * 100).toFixed(1)}%
                </div>
              ))}
            </div>
          )}
          {result.internal_matches > 0 && (
            <p className="text-xs text-muted mt-2">
              {result.internal_matches} internal match
              {result.internal_matches > 1 ? "es" : ""}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

/* ─── Expand ────────────────────────────────────────────── */

function ExpandTab() {
  const toast = useToastStore();
  const [text, setText] = useState("");
  const [sectionType, setSectionType] = useState("results");
  const [targetLength, setTargetLength] = useState("medium");
  const [level, setLevel] = useState("undergraduate");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    expanded_text: string;
    paragraph_count: number;
    word_count: number;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const expand = async () => {
    if (text.trim().length < 30) {
      toast.add("warning", "Paragraph must be at least 30 characters.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await api.post("/api/v1/research-writer/expand", {
        paragraph: text.trim(),
        section_type: sectionType,
        target_length: targetLength,
        level,
      });
      setResult(res.data);
    } catch {
      toast.add("error", "Expansion failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <Textarea
          label="Paragraph to Expand"
          rows={5}
          placeholder="Paste a paragraph to expand into a multi-paragraph section…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="grid sm:grid-cols-3 gap-3 mt-4">
          <SelectField label="Section" value={sectionType} onChange={setSectionType} options={["results", "discussion", "methodology", "analysis"]} />
          <SelectField label="Length" value={targetLength} onChange={setTargetLength} options={["medium", "full"]} />
          <SelectField label="Level" value={level} onChange={setLevel} options={["undergraduate", "masters", "phd"]} />
        </div>
        <Button onClick={expand} loading={loading} className="mt-4">
          <Expand className="w-4 h-4 mr-1" /> Expand
        </Button>
      </Card>

      {result && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <div className="flex gap-2">
              <Badge variant="default">{result.paragraph_count} paragraphs</Badge>
              <Badge variant="default">{result.word_count} words</Badge>
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(result.expanded_text);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="p-2 rounded-lg hover:bg-surface2 text-muted hover:text-txt transition-colors"
            >
              {copied ? <Check className="w-4 h-4 text-ok" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-sm text-txt/80 whitespace-pre-wrap leading-relaxed">
            {result.expanded_text}
          </p>
        </Card>
      )}
    </div>
  );
}

/* ─── Improve ───────────────────────────────────────────── */

function ImproveTab() {
  const toast = useToastStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [explanation, setExplanation] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const improve = async () => {
    if (!explanation.trim()) {
      toast.add("warning", "Enter your explanation.");
      return;
    }
    if (!imageFile && !imageUrl.trim()) {
      toast.add("warning", "Provide an image.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("explanation", explanation.trim());
      if (imageFile) fd.append("image", imageFile);
      else if (imageUrl.trim()) fd.append("image_url", imageUrl.trim());
      const res = await api.post("/api/v1/research-writer/improve", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data.improved_explanation);
    } catch {
      toast.add("error", "Improvement failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Improve your graph explanation to be more academic and precise.
        </p>
        <div className="grid sm:grid-cols-2 gap-4 mb-4">
          <div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                setImageFile(e.target.files?.[0] || null);
                setImageUrl("");
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full border-2 border-dashed border-border rounded-xl p-4 text-center hover:border-accent/50 transition-colors"
            >
              <Upload className="w-6 h-6 mx-auto text-muted mb-1" />
              <p className="text-xs text-muted">
                {imageFile ? imageFile.name : "Upload image"}
              </p>
            </button>
          </div>
          <Input
            label="Or Image URL"
            placeholder="https://…"
            value={imageUrl}
            onChange={(e) => {
              setImageUrl(e.target.value);
              setImageFile(null);
            }}
          />
        </div>
        <Textarea
          label="Your Explanation"
          rows={4}
          placeholder="Describe what you see in the graph…"
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
        />
        <Button onClick={improve} loading={loading} className="mt-4">
          <Wand2 className="w-4 h-4 mr-1" /> Improve
        </Button>
      </Card>

      {result && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-muted">
              Improved Explanation
            </h3>
            <button
              onClick={() => {
                navigator.clipboard.writeText(result);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="p-2 rounded-lg hover:bg-surface2 text-muted hover:text-txt transition-colors"
            >
              {copied ? <Check className="w-4 h-4 text-ok" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-sm text-txt/80 leading-relaxed">{result}</p>
        </Card>
      )}
    </div>
  );
}

/* ─── Caption ───────────────────────────────────────────── */

function CaptionTab() {
  const toast = useToastStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [explanation, setExplanation] = useState("");
  const [loading, setLoading] = useState(false);
  const [caption, setCaption] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    if (!imageFile && !imageUrl.trim()) {
      toast.add("warning", "Provide an image.");
      return;
    }
    setLoading(true);
    setCaption(null);
    try {
      const fd = new FormData();
      if (explanation.trim()) fd.append("explanation", explanation.trim());
      if (imageFile) fd.append("image", imageFile);
      else if (imageUrl.trim()) fd.append("image_url", imageUrl.trim());
      const res = await api.post("/api/v1/research-writer/caption", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setCaption(res.data.caption);
    } catch {
      toast.add("error", "Caption generation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Generate an academic figure caption from a graph image.
        </p>
        <div className="grid sm:grid-cols-2 gap-4 mb-4">
          <div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                setImageFile(e.target.files?.[0] || null);
                setImageUrl("");
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full border-2 border-dashed border-border rounded-xl p-4 text-center hover:border-accent/50 transition-colors"
            >
              <ImageIcon className="w-6 h-6 mx-auto text-muted mb-1" />
              <p className="text-xs text-muted">
                {imageFile ? imageFile.name : "Upload image"}
              </p>
            </button>
          </div>
          <Input
            label="Or Image URL"
            placeholder="https://…"
            value={imageUrl}
            onChange={(e) => {
              setImageUrl(e.target.value);
              setImageFile(null);
            }}
          />
        </div>
        <Textarea
          label="Explanation (optional)"
          rows={3}
          placeholder="Optionally describe the chart…"
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
        />
        <Button onClick={generate} loading={loading} className="mt-4">
          <ImageIcon className="w-4 h-4 mr-1" /> Generate Caption
        </Button>
      </Card>

      {caption && (
        <Card>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-muted">Caption</h3>
            <button
              onClick={() => {
                navigator.clipboard.writeText(caption);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="p-2 rounded-lg hover:bg-surface2 text-muted hover:text-txt transition-colors"
            >
              {copied ? <Check className="w-4 h-4 text-ok" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-sm text-txt/80 italic">{caption}</p>
        </Card>
      )}
    </div>
  );
}

/* ─── Sources ───────────────────────────────────────────── */

function SourcesTab() {
  const toast = useToastStore();
  const [topic, setTopic] = useState("");
  const [citationStyle, setCitationStyle] = useState("apa");
  const [maxResults, setMaxResults] = useState(8);
  const [loading, setLoading] = useState(false);
  const [sources, setSources] = useState<
    { title: string; authors: string[]; year: number; venue: string; source: string; formatted_citation: string }[]
  >([]);

  const search = async () => {
    if (topic.trim().length < 5) {
      toast.add("warning", "Topic must be at least 5 characters.");
      return;
    }
    setLoading(true);
    setSources([]);
    try {
      const res = await api.post("/api/v1/research-writer/find-sources", {
        topic: topic.trim(),
        max_results: maxResults,
        citation_style: citationStyle,
      });
      setSources(res.data.sources || []);
      toast.add("success", `Found ${res.data.source_count} sources.`);
    } catch {
      toast.add("error", "Source search failed.");
    } finally {
      setLoading(false);
    }
  };

  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const copyCitation = (citation: string, idx: number) => {
    navigator.clipboard.writeText(citation);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted mb-4">
          Search arXiv and OpenAlex for real academic papers.
        </p>
        <Input
          label="Research Topic"
          placeholder="e.g., Deep learning in medical imaging"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />
        <div className="grid sm:grid-cols-2 gap-3 mt-4">
          <SelectField
            label="Citation Style"
            value={citationStyle}
            onChange={setCitationStyle}
            options={["apa", "mla", "chicago"]}
          />
          <div>
            <label className="block text-xs font-medium text-muted mb-1">
              Max Results
            </label>
            <input
              type="number"
              min={1}
              max={20}
              value={maxResults}
              onChange={(e) => setMaxResults(Number(e.target.value))}
              className="w-full bg-surface border border-border rounded-xl px-3 py-2 text-sm text-txt focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
          </div>
        </div>
        <Button onClick={search} loading={loading} className="mt-4">
          <BookOpen className="w-4 h-4 mr-1" /> Find Sources
        </Button>
      </Card>

      {sources.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-muted mb-4">
            {sources.length} Sources Found
          </h3>
          <div className="space-y-3">
            {sources.map((s, i) => (
              <div key={i} className="p-3 bg-bg rounded-xl">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium mb-1">{s.title}</p>
                    <p className="text-xs text-muted">
                      {s.authors.slice(0, 3).join(", ")}
                      {s.authors.length > 3 ? " et al." : ""} ({s.year})
                    </p>
                    <p className="text-xs text-muted">{s.venue}</p>
                    <p className="text-xs text-txt/60 mt-1 italic">
                      {s.formatted_citation}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Badge variant="default">{s.source}</Badge>
                    <button
                      onClick={() => copyCitation(s.formatted_citation, i)}
                      className="p-1 rounded hover:bg-surface2 text-muted hover:text-txt transition-colors"
                      title="Copy citation"
                    >
                      {copiedIdx === i ? (
                        <Check className="w-3.5 h-3.5 text-ok" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ─── Shared ────────────────────────────────────────────── */

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
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
