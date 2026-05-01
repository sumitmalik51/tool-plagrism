import { AlertTriangle, ExternalLink } from "lucide-react";

export default function ReportPreview() {
  return (
    <div className="max-w-4xl mx-auto">
      {/* Score bar */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="bg-surface border border-border rounded-xl p-3 text-center">
          <p className="text-[10px] text-muted uppercase tracking-wider">Plagiarism</p>
          <p className="text-xl font-bold text-danger">34%</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-3 text-center">
          <p className="text-[10px] text-muted uppercase tracking-wider">Original</p>
          <p className="text-xl font-bold text-ok">66%</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-3 text-center">
          <p className="text-[10px] text-muted uppercase tracking-wider">AI Content</p>
          <p className="text-xl font-bold text-accent-l">12%</p>
        </div>
        <div className="bg-surface border border-border rounded-xl p-3 text-center">
          <p className="text-[10px] text-muted uppercase tracking-wider">Risk</p>
          <span className="inline-flex items-center gap-1 text-warn text-sm font-semibold">
            <AlertTriangle className="w-3 h-3" /> Medium
          </span>
        </div>
      </div>

      {/* Highlighted text preview */}
      <div className="bg-surface border border-border rounded-xl p-5 mb-6">
        <p className="text-[10px] font-semibold text-muted uppercase tracking-wider mb-3">Highlighted Text Preview</p>
        <p className="text-sm leading-relaxed text-txt/80">
          Artificial intelligence has revolutionized the way we process and analyze large datasets.{" "}
          <span className="bg-danger/15 text-danger px-0.5 rounded border-b border-danger/40">
            Machine learning algorithms can identify patterns in data that would be impossible for humans to detect manually.
          </span>{" "}
          <span className="bg-warn/15 text-warn px-0.5 rounded border-b border-warn/40">
            Deep learning, a subset of machine learning, uses neural networks with multiple layers to learn hierarchical representations of data.
          </span>{" "}
          These technologies have found applications in healthcare, finance, natural language processing, and autonomous vehicles.
        </p>
        <div className="flex items-center gap-4 mt-3 text-[10px] text-muted">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-danger" /> Direct match</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-warn" /> Paraphrase</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-accent-l" /> AI-generated</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-ok" /> Original</span>
        </div>
      </div>

      {/* Sources mini-list */}
      <div className="bg-surface border border-border rounded-xl p-5">
        <p className="text-[10px] font-semibold text-muted uppercase tracking-wider mb-3">Matched Sources</p>
        <div className="space-y-2">
          {[
            { pct: 28, title: "Introduction to Machine Learning — MIT OpenCourseWare", url: "ocw.mit.edu" },
            { pct: 19, title: "Deep Learning for Beginners — Stanford CS231n", url: "cs231n.stanford.edu" },
            { pct: 11, title: "AI in Healthcare: A Review — Nature Medicine", url: "nature.com" },
          ].map((s, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center text-accent text-xs font-bold shrink-0">
                {s.pct}%
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate">{s.title}</p>
                <p className="text-[10px] text-muted flex items-center gap-1"><ExternalLink className="w-2.5 h-2.5" /> {s.url}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
