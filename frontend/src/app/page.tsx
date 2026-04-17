import Link from "next/link";
import {
  Shield,
  Bot,
  FileSearch,
  PenLine,
  BookOpen,
  Check,
  ArrowRight,
  Sparkles,
} from "lucide-react";

const FEATURES = [
  {
    icon: <Shield className="w-6 h-6" />,
    title: "Plagiarism Detection",
    desc: "Multi-source scanning across web, academic, and internal databases.",
  },
  {
    icon: <Bot className="w-6 h-6" />,
    title: "AI Content Detection",
    desc: "Identify AI-generated text with GPT, Claude, and LLM pattern analysis.",
  },
  {
    icon: <FileSearch className="w-6 h-6" />,
    title: "Source Attribution",
    desc: "Detailed source matching with similarity scores and passage highlighting.",
  },
  {
    icon: <PenLine className="w-6 h-6" />,
    title: "Smart Rewriter",
    desc: "7 rewrite modes with tone and strength controls. Export to DOCX.",
  },
  {
    icon: <Sparkles className="w-6 h-6" />,
    title: "Research Writer",
    desc: "Generate academic paragraphs from charts/graphs with real citations.",
  },
  {
    icon: <BookOpen className="w-6 h-6" />,
    title: "Grammar & Readability",
    desc: "Inline error detection, Flesch-Kincaid scores, and improvement tips.",
  },
];

const STATS = [
  { value: "10M+", label: "Documents Scanned" },
  { value: "50K+", label: "Active Users" },
  { value: "99.2%", label: "Detection Accuracy" },
  { value: "< 30s", label: "Average Scan Time" },
];

const FAQ = [
  {
    q: "How accurate is the plagiarism detection?",
    a: "Our multi-agent system achieves 99.2% accuracy by combining web search, academic databases, and AI analysis.",
  },
  {
    q: "What file formats are supported?",
    a: "PDF, DOCX, TXT, LaTeX (.tex), and PPTX. You can also paste text directly or import from Google Docs.",
  },
  {
    q: "Is my data secure?",
    a: "Yes. Documents are encrypted in transit and at rest. We never share your content with third parties.",
  },
  {
    q: "Can I use this for my institution?",
    a: "Yes! Our Premium plan includes API access and batch processing for institutional use.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-bg text-txt">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-accent" />
            <span className="text-lg font-bold">PlagiarismGuard</span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/pricing"
              className="text-sm text-muted hover:text-txt transition-colors hidden sm:block"
            >
              Pricing
            </Link>
            <Link
              href="/login"
              className="text-sm text-muted hover:text-txt transition-colors"
            >
              Sign In
            </Link>
            <Link
              href="/signup"
              className="px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-medium rounded-xl transition-colors"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-4 py-24 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-accent/10 text-accent-l text-sm rounded-full mb-6">
          <Sparkles className="w-4 h-4" />
          AI-Powered Analysis
        </div>
        <h1 className="text-5xl sm:text-6xl font-bold leading-tight mb-6">
          Detect Plagiarism.
          <br />
          <span className="text-accent">Verify Originality.</span>
        </h1>
        <p className="text-lg text-muted max-w-2xl mx-auto mb-10">
          Advanced multi-agent plagiarism detection with AI content analysis,
          smart rewriting, and academic research tools — all in one platform.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link
            href="/signup"
            className="inline-flex items-center justify-center gap-2 px-8 py-3 bg-accent hover:bg-accent/90 text-white font-medium rounded-xl transition-colors text-lg"
          >
            Start Free <ArrowRight className="w-5 h-5" />
          </Link>
          <Link
            href="/pricing"
            className="inline-flex items-center justify-center gap-2 px-8 py-3 bg-surface border border-border hover:bg-surface2 text-txt font-medium rounded-xl transition-colors text-lg"
          >
            View Plans
          </Link>
        </div>
      </section>

      {/* Stats */}
      <section className="border-y border-border bg-surface/50">
        <div className="max-w-5xl mx-auto px-4 py-12 grid grid-cols-2 sm:grid-cols-4 gap-8">
          {STATS.map((s, i) => (
            <div key={i} className="text-center">
              <p className="text-3xl font-bold text-accent">{s.value}</p>
              <p className="text-sm text-muted mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-4 py-20">
        <h2 className="text-3xl font-bold text-center mb-12">
          Everything You Need
        </h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((f, i) => (
            <div
              key={i}
              className="bg-surface border border-border rounded-2xl p-6 hover:border-accent/30 transition-colors"
            >
              <div className="text-accent mb-3">{f.icon}</div>
              <h3 className="text-lg font-semibold mb-2">{f.title}</h3>
              <p className="text-sm text-muted">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Research Writer spotlight */}
      <section className="border-y border-border bg-surface/30">
        <div className="max-w-4xl mx-auto px-4 py-20 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-accent/10 text-accent-l text-xs font-medium rounded-full mb-4">
            NEW
          </div>
          <h2 className="text-3xl font-bold mb-4">Research Writer</h2>
          <p className="text-muted max-w-xl mx-auto mb-8">
            Upload a graph or chart, describe your findings, and get a
            publication-ready paragraph with real academic citations from arXiv
            and OpenAlex.
          </p>
          <div className="grid sm:grid-cols-3 gap-4 text-left">
            {[
              "Graph-to-paragraph generation",
              "Real academic citations (APA, MLA, Chicago)",
              "Plagiarism check on generated text",
              "Expand paragraphs into full sections",
              "Improve your explanations",
              "Auto figure captions",
            ].map((item, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-sm text-txt/80"
              >
                <Check className="w-4 h-4 text-ok shrink-0 mt-0.5" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="max-w-3xl mx-auto px-4 py-20">
        <h2 className="text-3xl font-bold text-center mb-12">FAQ</h2>
        <div className="space-y-4">
          {FAQ.map((faq, i) => (
            <details
              key={i}
              className="bg-surface border border-border rounded-2xl overflow-hidden"
            >
              <summary className="px-6 py-4 cursor-pointer text-sm font-medium hover:text-accent transition-colors">
                {faq.q}
              </summary>
              <div className="px-6 pb-4">
                <p className="text-sm text-muted">{faq.a}</p>
              </div>
            </details>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-4xl mx-auto px-4 py-20 text-center">
        <h2 className="text-3xl font-bold mb-4">
          Ready to Verify Your Work?
        </h2>
        <p className="text-muted mb-8">
          Join thousands of students, researchers, and institutions.
        </p>
        <Link
          href="/signup"
          className="inline-flex items-center gap-2 px-8 py-3 bg-accent hover:bg-accent/90 text-white font-medium rounded-xl transition-colors text-lg"
        >
          Create Free Account <ArrowRight className="w-5 h-5" />
        </Link>
      </section>

      {/* Footer */}
      <footer className="border-t border-border bg-surface/30">
        <div className="max-w-5xl mx-auto px-4 py-12">
          <div className="grid sm:grid-cols-4 gap-8">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-5 h-5 text-accent" />
                <span className="font-bold">PlagiarismGuard</span>
              </div>
              <p className="text-xs text-muted">
                AI-powered plagiarism detection and writing tools.
              </p>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Product</h4>
              <div className="space-y-2">
                <Link href="/pricing" className="block text-xs text-muted hover:text-txt">
                  Pricing
                </Link>
                <Link href="/api-docs" className="block text-xs text-muted hover:text-txt">
                  API Docs
                </Link>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Company</h4>
              <div className="space-y-2">
                <Link href="/about" className="block text-xs text-muted hover:text-txt">
                  About
                </Link>
                <Link href="/privacy" className="block text-xs text-muted hover:text-txt">
                  Privacy
                </Link>
                <Link href="/terms" className="block text-xs text-muted hover:text-txt">
                  Terms
                </Link>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Support</h4>
              <div className="space-y-2">
                <span className="block text-xs text-muted">
                  support@plagiarismguard.com
                </span>
              </div>
            </div>
          </div>
          <div className="border-t border-border mt-8 pt-6 text-center">
            <p className="text-xs text-muted">
              &copy; {new Date().getFullYear()} PlagiarismGuard. All rights
              reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
