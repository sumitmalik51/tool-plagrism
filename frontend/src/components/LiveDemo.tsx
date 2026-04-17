"use client";

import { useState, useEffect } from "react";
import { ArrowRight, AlertTriangle, ExternalLink, Search, BookOpen, Bot, Brain, FileSearch, Check } from "lucide-react";

const SAMPLE_TEXT = `Artificial intelligence has revolutionized the way we process and analyze large datasets. Machine learning algorithms can identify patterns in data that would be impossible for humans to detect manually. Deep learning, a subset of machine learning, uses neural networks with multiple layers to learn hierarchical representations of data. These technologies have found applications in healthcare, finance, natural language processing, and autonomous vehicles.`;

const FAKE_RESULT = {
  plagiarismScore: 34,
  originalScore: 66,
  aiScore: 12,
  riskLevel: "Medium" as const,
  sources: [
    { title: "Introduction to Machine Learning — MIT OpenCourseWare", url: "https://ocw.mit.edu/ml-intro", similarity: 28 },
    { title: "Deep Learning for Beginners — Stanford CS231n", url: "https://cs231n.stanford.edu", similarity: 19 },
    { title: "AI in Healthcare: A Review — Nature Medicine", url: "https://nature.com/articles/ai-healthcare", similarity: 11 },
  ],
  flaggedPassages: [
    { text: "Machine learning algorithms can identify patterns in data that would be impossible for humans to detect manually.", source: "MIT OpenCourseWare", similarity: 28, type: "direct" as const },
    { text: "Deep learning, a subset of machine learning, uses neural networks with multiple layers to learn hierarchical representations of data.", source: "Stanford CS231n", similarity: 19, type: "paraphrase" as const },
  ],
};

const AGENT_STEPS = [
  { agent: "Web Search Agent", icon: <Search className="w-4 h-4" />, action: "Scanning web pages for content matches..." },
  { agent: "Web Search Agent", icon: <Search className="w-4 h-4" />, action: "Found 3 matching sources across web indexes" },
  { agent: "Academic Agent", icon: <BookOpen className="w-4 h-4" />, action: "Querying arXiv and OpenAlex databases..." },
  { agent: "Academic Agent", icon: <BookOpen className="w-4 h-4" />, action: "Cross-referencing 2 academic papers" },
  { agent: "AI Detection Agent", icon: <Bot className="w-4 h-4" />, action: "Analyzing perplexity and burstiness patterns..." },
  { agent: "AI Detection Agent", icon: <Bot className="w-4 h-4" />, action: "AI content probability: 12% (low confidence)" },
  { agent: "Semantic Agent", icon: <Brain className="w-4 h-4" />, action: "Computing semantic embeddings..." },
  { agent: "Semantic Agent", icon: <Brain className="w-4 h-4" />, action: "Detected 1 paraphrased passage (19% similarity)" },
  { agent: "Report Agent", icon: <FileSearch className="w-4 h-4" />, action: "Aggregating findings from all agents..." },
  { agent: "Report Agent", icon: <FileSearch className="w-4 h-4" />, action: "Report generated — Risk Level: Medium" },
];

export default function LiveDemo() {
  const [text, setText] = useState("");
  const [showResult, setShowResult] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);

  useEffect(() => {
    if (!analyzing) return;
    if (currentStep >= AGENT_STEPS.length - 1) {
      const timer = setTimeout(() => {
        setAnalyzing(false);
        setShowResult(true);
        setCurrentStep(-1);
        setCompletedSteps([]);
      }, 600);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => {
      setCurrentStep((s) => {
        const next = s + 1;
        setCompletedSteps((prev) => (s >= 0 ? [...prev, s] : prev));
        return next;
      });
    }, 400);
    return () => clearTimeout(timer);
  }, [analyzing, currentStep]);

  function handleAnalyze() {
    if (!text.trim()) {
      setText(SAMPLE_TEXT);
      return;
    }
    setAnalyzing(true);
    setCurrentStep(-1);
    setCompletedSteps([]);
    // kick off the first step
    setTimeout(() => setCurrentStep(0), 300);
  }

  function handleReset() {
    setShowResult(false);
    setText("");
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-20">
      <div className="text-center mb-10">
        <p className="text-xs font-semibold text-accent uppercase tracking-widest mb-3">LIVE DEMO</p>
        <h2 className="text-3xl font-bold mb-3">Try It Now — See Results Instantly</h2>
        <p className="text-muted">Paste your content and watch our multi-agent system analyze it in real time. No sign-up required.</p>
      </div>

      {!showResult ? (
        <div className="bg-surface border border-border rounded-2xl p-6 sm:p-8">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            disabled={analyzing}
            placeholder="Paste your text here to check for plagiarism... or click Analyze to try with sample text."
            className="w-full bg-bg border border-border rounded-xl p-4 text-sm text-txt placeholder:text-muted/60 resize-none focus:outline-none focus:border-accent/50 disabled:opacity-50"
          />

          {/* Agent progress panel */}
          {analyzing && currentStep >= 0 && (
            <div className="mt-4 bg-bg border border-border rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-semibold text-accent uppercase tracking-wider">Multi-Agent Analysis Running</p>
                <p className="text-xs text-muted">{Math.min(currentStep + 1, AGENT_STEPS.length)}/{AGENT_STEPS.length} steps</p>
              </div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {AGENT_STEPS.map((step, i) => {
                  const isCompleted = completedSteps.includes(i);
                  const isCurrent = i === currentStep;
                  const isPending = i > currentStep;
                  return (
                    <div
                      key={i}
                      className={`flex items-center gap-2.5 text-xs px-3 py-1.5 rounded-lg transition-all duration-300 ${
                        isCurrent ? "bg-accent/10 text-accent" : isCompleted ? "text-ok/80" : isPending ? "text-muted/30" : "text-muted"
                      }`}
                    >
                      {isCompleted ? (
                        <Check className="w-3.5 h-3.5 text-ok shrink-0" />
                      ) : isCurrent ? (
                        <span className="w-3.5 h-3.5 border-2 border-accent/30 border-t-accent rounded-full animate-spin shrink-0" />
                      ) : (
                        <span className="w-3.5 h-3.5 shrink-0">{step.icon}</span>
                      )}
                      <span className="font-medium">{step.agent}</span>
                      <span className="text-muted/70">—</span>
                      <span>{step.action}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between mt-4">
            <span className="text-xs text-muted">{text.length} characters</span>
            <button
              onClick={handleAnalyze}
              disabled={analyzing}
              className="inline-flex items-center gap-2 px-6 py-2.5 bg-accent hover:bg-accent/90 disabled:opacity-60 text-white text-sm font-medium rounded-xl transition-colors"
            >
              {analyzing ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  Analyze <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Score cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <ScoreCard label="Plagiarism" value={`${FAKE_RESULT.plagiarismScore}%`} color="text-danger" />
            <ScoreCard label="Original" value={`${FAKE_RESULT.originalScore}%`} color="text-ok" />
            <ScoreCard label="AI Content" value={`${FAKE_RESULT.aiScore}%`} color="text-accent-l" />
            <div className="bg-surface border border-border rounded-2xl p-4 text-center">
              <p className="text-xs text-muted mb-1">Risk Level</p>
              <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-warn/15 text-warn text-sm font-semibold rounded-full">
                <AlertTriangle className="w-3.5 h-3.5" />
                {FAKE_RESULT.riskLevel}
              </span>
            </div>
          </div>

          {/* Flagged passages */}
          <div className="bg-surface border border-border rounded-2xl p-6">
            <h3 className="text-sm font-semibold mb-4">Flagged Passages</h3>
            <div className="space-y-3">
              {FAKE_RESULT.flaggedPassages.map((p, i) => (
                <div key={i} className={`border-l-3 rounded-lg p-4 bg-bg ${p.type === "direct" ? "border-danger" : "border-warn"}`}>
                  <p className="text-sm mb-2 leading-relaxed">
                    <span className={`${p.type === "direct" ? "bg-danger/15 text-danger" : "bg-warn/15 text-warn"} px-1 rounded`}>
                      {p.text}
                    </span>
                  </p>
                  <div className="flex items-center gap-3 text-xs text-muted">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium uppercase ${p.type === "direct" ? "bg-danger/15 text-danger" : "bg-warn/15 text-warn"}`}>
                      {p.type}
                    </span>
                    <span>{p.similarity}% match</span>
                    <span>— {p.source}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Sources */}
          <div className="bg-surface border border-border rounded-2xl p-6">
            <h3 className="text-sm font-semibold mb-4">Sources Found</h3>
            <div className="space-y-2">
              {FAKE_RESULT.sources.map((s, i) => (
                <div key={i} className="flex items-center gap-3 p-3 bg-bg rounded-xl">
                  <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center text-accent text-sm font-bold shrink-0">
                    {s.similarity}%
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{s.title}</p>
                    <p className="text-xs text-muted truncate flex items-center gap-1">
                      <ExternalLink className="w-3 h-3" /> {s.url}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* CTA under demo */}
          <div className="text-center pt-2 space-y-3">
            <p className="text-sm text-muted">This is a preview. Sign up for full reports with PDF export, history, and more.</p>
            <div className="flex items-center justify-center gap-3">
              <button onClick={handleReset} className="px-5 py-2 bg-surface border border-border hover:bg-surface2 text-sm font-medium rounded-xl transition-colors">
                Try Again
              </button>
              <a href="/signup" className="inline-flex items-center gap-2 px-5 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-medium rounded-xl transition-colors">
                Get Full Access <ArrowRight className="w-4 h-4" />
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4 text-center">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}
