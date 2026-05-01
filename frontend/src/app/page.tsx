import Link from "next/link";
import {
  Shield,
  PenLine,
  Check,
  ArrowRight,
  FlaskConical,
  Globe,
  FileText,
  Search,
  BookOpen,
  Lock,
  Download,
  Users,
  Plug,
  Layers,
  Fingerprint,
  ShieldCheck,
  GraduationCap,
  Building2,
  UserCheck,
  FileCheck,
  Award,
  Briefcase,
  PenTool,
  Scale,
  ChevronDown,
  AlertTriangle,
  Gavel,
} from "lucide-react";
import LiveDemo from "@/components/LiveDemo";
import AnimatedCounter from "@/components/AnimatedCounter";
import AgentAccordion from "@/components/AgentAccordion";
import ReportPreview from "@/components/ReportPreview";
import ConsensusToggle from "@/components/ConsensusToggle";
import PipelineFlow from "@/components/PipelineFlow";
import ScrollToTop from "@/components/ScrollToTop";
import ThemeToggle from "@/components/ThemeToggle";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-bg text-txt">
      <ScrollToTop />
      {/* ═══ NAVBAR ═══ */}
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-accent" />
            <span className="text-lg font-bold">PlagiarismGuard</span>
          </div>
          <div className="hidden md:flex items-center gap-6 text-sm text-muted">
            <a href="#engine" className="hover:text-txt transition-colors">How It Works</a>
            <a href="#agents" className="hover:text-txt transition-colors">Agents</a>
            <a href="#demo" className="hover:text-txt transition-colors">Demo</a>
            <a href="#cases" className="hover:text-txt transition-colors">Why Now</a>
            <Link href="/pricing" className="hover:text-txt transition-colors">Pricing</Link>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link href="/login" className="text-sm text-muted hover:text-txt transition-colors">Sign In</Link>
            <Link href="/signup" className="px-4 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-medium rounded-xl transition-colors">
              Get Started Free
            </Link>
          </div>
        </div>
      </nav>

      {/* ═══ HERO — philosophical thesis ═══ */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-accent/[0.04] to-transparent pointer-events-none" />
        {/* subtle grid */}
        <div
          className="absolute inset-0 opacity-[0.04] pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)",
            backgroundSize: "64px 64px",
            color: "var(--txt)",
          }}
        />
        <div className="max-w-4xl mx-auto px-4 pt-32 pb-24 text-center relative">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-8">
            Multi-Agent Originality Analysis
          </p>
          <h1 className="text-5xl sm:text-[64px] font-bold leading-[1.05] mb-8 tracking-tight">
            Originality isn&apos;t a score.
            <br />
            <span className="text-muted">It&apos;s a trail of evidence.</span>
          </h1>
          <p className="text-lg text-muted max-w-2xl mx-auto mb-10 leading-relaxed">
            Most tools return a single number and call it detection. PlagiarismGuard runs five specialized
            AI agents in parallel — each producing verifiable evidence. Every flag is sourced, every claim
            is attributed, every report is defensible.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-txt hover:bg-txt/90 text-bg font-semibold rounded-full transition-colors text-sm"
            >
              Try It Free <ArrowRight className="w-4 h-4" />
            </Link>
            <a
              href="#demo"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-transparent border border-border hover:border-txt/40 text-txt font-medium rounded-full transition-colors text-sm"
            >
              See how it works
            </a>
          </div>

          {/* hero sub-proof — four inline metrics, thin dividers */}
          <div className="mt-20 grid grid-cols-2 sm:grid-cols-4 max-w-3xl mx-auto border-t border-b border-border/60 divide-x divide-border/60">
            {[
              { v: <AnimatedCounter target={5} />, l: "agents per scan" },
              { v: "99.2%", l: "detection accuracy" },
              { v: <AnimatedCounter target={10} suffix="M+" />, l: "documents scanned" },
              { v: "< 30s", l: "average result" },
            ].map((s, i) => (
              <div key={i} className="py-5 px-2">
                <p className="text-xl font-bold text-txt">{s.v}</p>
                <p className="text-[11px] uppercase tracking-wider text-muted mt-1">{s.l}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ THE PROBLEM — interactive toggle ═══ */}
      <section className="max-w-4xl mx-auto px-4 py-24">
        <div className="text-center mb-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">The Problem</p>
          <h2 className="text-4xl font-bold mb-5 tracking-tight">
            Every plagiarism tool returns a number.
            <br />
            <span className="text-muted">Numbers aren&apos;t evidence.</span>
          </h2>
          <p className="text-muted max-w-2xl mx-auto leading-relaxed">
            A single-model checker can say &ldquo;8% plagiarism&rdquo; while missing AI-generated paragraphs,
            paraphrased research, and uncited academic sources. Toggle below to see the same text analyzed
            both ways.
          </p>
        </div>

        <ConsensusToggle />
      </section>

      {/* ═══ THE CONSENSUS ENGINE — named framework ═══ */}
      <section id="engine" className="bg-surface/30 border-y border-border/60">
        <div className="max-w-5xl mx-auto px-4 py-24">
          <div className="text-center mb-12">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">The Consensus Engine</p>
            <h2 className="text-4xl font-bold mb-5 tracking-tight">
              Every document flows through
              <br />
              <span className="text-muted">three stages of verification.</span>
            </h2>
            <p className="text-muted max-w-2xl mx-auto leading-relaxed">
              Before any result reaches you, it passes through our proprietary three-stage engine —
              built specifically for defensible originality analysis. Scan detects. Verify cross-checks.
              Attribute sources and proves it.
            </p>
          </div>

          {/* Pipeline flow \u2014 animated */}
          <PipelineFlow />

          {/* 3 stages */}
          <div className="grid md:grid-cols-3 gap-6">
            {[
              {
                stage: "Stage 01",
                name: "Scan",
                title: "Multi-Agent Detection",
                desc: "Five specialized agents scan your text in parallel — web, academic, AI-fingerprint, semantic, and aggregation. Each runs independently with its own detection model.",
                points: [
                  "Web Search Agent — billions of pages",
                  "Academic Agent — arXiv, OpenAlex, Semantic Scholar",
                  "AI Detection Agent — perplexity + burstiness",
                  "Semantic Agent — embedding-based paraphrase detection",
                ],
                icon: <Search className="w-4 h-4" />,
              },
              {
                stage: "Stage 02",
                name: "Verify",
                title: "Cross-Agent Consensus",
                desc: "Findings from each agent are compared, weighted by confidence, and deduplicated. Disagreements trigger re-analysis. False positives from any single agent get filtered out.",
                points: [
                  "Confidence-weighted scoring across 5 agents",
                  "Deduplication of overlapping source matches",
                  "Conflict resolution between detectors",
                  "Common phrases & cited quotes de-weighted",
                ],
                icon: <ShieldCheck className="w-4 h-4" />,
              },
              {
                stage: "Stage 03",
                name: "Attribute",
                title: "Source & Audit Trail",
                desc: "Every flagged passage is mapped to its source. Every claim includes a URL, confidence interval, and classification. You get an exportable audit trail — not just a number.",
                points: [
                  "Passage-level source attribution with URLs",
                  "Direct copy vs. paraphrase classification",
                  "Confidence intervals per finding",
                  "PDF audit trail exportable per document",
                ],
                icon: <Fingerprint className="w-4 h-4" />,
              },
            ].map((s) => (
              <div key={s.name} className="bg-bg border border-border/60 rounded-2xl p-6">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-3">{s.stage}</p>
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-txt">{s.icon}</span>
                  <h3 className="text-xl font-bold">{s.name}</h3>
                </div>
                <p className="text-sm font-medium text-txt mb-2">{s.title}</p>
                <p className="text-sm text-muted mb-5 leading-relaxed">{s.desc}</p>
                <div className="pt-4 border-t border-border/60 space-y-2">
                  {s.points.map((p, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-muted">
                      <span className="w-1 h-1 rounded-full bg-muted/50 mt-1.5 shrink-0" />
                      {p}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ LIVE DEMO ═══ */}
      <section id="demo" className="border-y border-border/60 bg-surface/20">
        <LiveDemo />
      </section>

      {/* ═══ VISUAL PROOF — report preview ═══ */}
      <section className="max-w-4xl mx-auto px-4 py-24">
        <div className="text-center mb-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">The Report</p>
          <h2 className="text-4xl font-bold mb-5 tracking-tight">
            Evidence, not just a number.
          </h2>
          <p className="text-muted max-w-lg mx-auto leading-relaxed">
            Highlighted text, source attributions, confidence intervals, matched URLs — every finding is inspectable.
          </p>
        </div>

        <div className="bg-bg border border-border/60 rounded-2xl p-6 sm:p-8">
          <ReportPreview />
        </div>
      </section>

      {/* ═══ AGENTS — accordion (show less, reveal more) ═══ */}
      <section id="agents" className="bg-surface/30 border-y border-border/60">
        <div className="max-w-3xl mx-auto px-4 py-24">
          <div className="text-center mb-10">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">The Agents</p>
            <h2 className="text-4xl font-bold mb-5 tracking-tight">
              Five agents. Independent analysis.
              <br />
              <span className="text-muted">Consensus-driven results.</span>
            </h2>
            <p className="text-muted max-w-2xl mx-auto leading-relaxed">
              Each agent examines a different dimension of your text. Click any agent to see exactly how it works.
            </p>
          </div>

          <AgentAccordion />
        </div>
      </section>

      {/* ═══ FEATURES — editorial list style ═══ */}
      <section id="features" className="max-w-4xl mx-auto px-4 py-24">
        <div className="text-center mb-12">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">The Platform</p>
          <h2 className="text-4xl font-bold mb-5 tracking-tight">
            Detection is step one.
            <br />
            <span className="text-muted">Here&apos;s everything else.</span>
          </h2>
          <p className="text-muted max-w-2xl mx-auto leading-relaxed">
            A full originality platform — not just a checker. Detect, fix, rewrite, and research, all in one place.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-px bg-border/60 border border-border/60 rounded-2xl overflow-hidden">
          {/* Detection Engine */}
          <div className="bg-bg p-8">
            <Shield className="w-5 h-5 text-txt mb-4" />
            <h3 className="text-lg font-semibold mb-4">Detection Engine</h3>
            <ul className="space-y-3 text-sm text-muted">
              {[
                "Multi-source scanning — web, arXiv, OpenAlex, Semantic Scholar",
                "AI content detection for GPT-4, Claude, Gemini, LLaMA",
                "Source attribution with confidence intervals",
                "Batch processing up to 50 files",
              ].map((t, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-1 h-1 rounded-full bg-muted/50 mt-2 shrink-0" />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          {/* Writing Tools */}
          <div className="bg-bg p-8">
            <PenLine className="w-5 h-5 text-txt mb-4" />
            <h3 className="text-lg font-semibold mb-4">Writing Tools</h3>
            <ul className="space-y-3 text-sm text-muted">
              {[
                "Smart Rewriter — 7 modes, 3 variations each",
                "Grammar Checker — inline, categorized, one-click fix",
                "Readability — 6 scores with improvement tips",
                "DOCX export for every rewrite",
              ].map((t, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-1 h-1 rounded-full bg-muted/50 mt-2 shrink-0" />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          {/* Research Writer */}
          <div className="bg-bg p-8">
            <FlaskConical className="w-5 h-5 text-txt mb-4" />
            <h3 className="text-lg font-semibold mb-4">Research Writer</h3>
            <ul className="space-y-3 text-sm text-muted">
              {[
                "Graph → paragraph with real citations",
                "Citation finder across arXiv + OpenAlex",
                "Auto-format APA, MLA, Chicago",
                "Section expander for full drafts",
              ].map((t, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-1 h-1 rounded-full bg-muted/50 mt-2 shrink-0" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ═══ PERSONAS — categorized icon cards ═══ */}
      <section id="use-cases" className="bg-surface/30 border-y border-border/60">
        <div className="max-w-4xl mx-auto px-4 py-24">
          <div className="text-center mb-12">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">Built For</p>
            <h2 className="text-4xl font-bold mb-5 tracking-tight">
              The people responsible for
              <br />
              <span className="text-muted">originality and integrity.</span>
            </h2>
            <p className="text-muted max-w-2xl mx-auto leading-relaxed">
              PlagiarismGuard serves every role in the academic and publishing chain — with visibility
              and evidence tailored to each.
            </p>
          </div>

          {/* 3 categories */}
          <div className="space-y-12">
            {[
              {
                category: "Academic",
                roles: [
                  {
                    icon: <Scale className="w-4 h-4" />,
                    role: "Academic Integrity Officers",
                    desc: "Real-time dashboard of every student submission with verification status, AI detection scores, and source attributions. Audit-ready reports, generated automatically.",
                  },
                  {
                    icon: <UserCheck className="w-4 h-4" />,
                    role: "Dissertation Supervisors",
                    desc: "See exactly what your student's checker will find — before submission. Source-mapped flagged passages, with confidence per finding.",
                  },
                  {
                    icon: <GraduationCap className="w-4 h-4" />,
                    role: "Students & Independent Writers",
                    desc: "Check your work before your institution does. Fix flagged passages with the built-in rewriter — and ship with confidence.",
                  },
                ],
              },
              {
                category: "Publishing",
                roles: [
                  {
                    icon: <FileCheck className="w-4 h-4" />,
                    role: "Journal Editors & Peer Reviewers",
                    desc: "Screen manuscripts for plagiarism, paraphrased content, and AI-generated passages before acceptance. Evidence-backed rejections, not just percentages.",
                  },
                  {
                    icon: <Building2 className="w-4 h-4" />,
                    role: "Publishing Houses",
                    desc: "Author submissions cross-checked against the web and academic databases. Compliance-ready audit trails for every accepted manuscript.",
                  },
                  {
                    icon: <Award className="w-4 h-4" />,
                    role: "Grant & Scholarship Reviewers",
                    desc: "Verify the originality of applications at scale. Consistent, defensible criteria for rejecting duplicated or AI-generated proposals.",
                  },
                ],
              },
              {
                category: "Enterprise",
                roles: [
                  {
                    icon: <FlaskConical className="w-4 h-4" />,
                    role: "Research Group Leaders",
                    desc: "Cross-check every co-author's contribution against arXiv and OpenAlex. Catch AI-generated sections in collaborative drafts before journal submission.",
                  },
                  {
                    icon: <Briefcase className="w-4 h-4" />,
                    role: "Content Agency Owners",
                    desc: "Batch-verify 50 articles at once. Guarantee originality to clients with exportable reports. Detect AI use in outsourced writer drafts.",
                  },
                  {
                    icon: <PenTool className="w-4 h-4" />,
                    role: "Editorial Teams",
                    desc: "Route flagged submissions to specialist reviewers with full evidence trails. Keep originality standards consistent across contributors.",
                  },
                ],
              },
            ].map((group) => (
              <div key={group.category}>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-5">
                  {group.category}
                </p>
                <div className="grid md:grid-cols-3 gap-px bg-border/60 border border-border/60 rounded-2xl overflow-hidden">
                  {group.roles.map((p) => (
                    <div
                      key={p.role}
                      className="group bg-bg hover:bg-surface/40 p-6 transition-colors cursor-default"
                    >
                      <div className="flex items-center gap-2 mb-3 text-txt/80 group-hover:text-accent transition-colors">
                        <span className="w-8 h-8 rounded-lg bg-surface border border-border/60 flex items-center justify-center group-hover:border-accent/40 group-hover:bg-accent/5 transition-colors">
                          {p.icon}
                        </span>
                      </div>
                      <h3 className="text-sm font-semibold mb-2 leading-snug">{p.role}</h3>
                      <p className="text-[13px] text-muted leading-relaxed">{p.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ WHY NOW — alarming stat cards ═══ */}
      <section id="cases" className="max-w-4xl mx-auto px-4 py-24">
        <div className="text-center mb-12">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">Why Now</p>
          <h2 className="text-4xl font-bold mb-5 tracking-tight">
            The stakes just got higher.
          </h2>
          <p className="text-muted max-w-2xl mx-auto leading-relaxed">
            AI-assisted writing is now ubiquitous — and institutions are responding. Single-model checkers
            can&apos;t keep up with the pace of change.
          </p>
        </div>

        {/* Alarming stat cards */}
        <div className="grid md:grid-cols-3 gap-4 mb-16">
          {[
            {
              tag: "Higher Education",
              year: "2024",
              stat: "3,600+",
              statLabel: "integrity cases flagged",
              icon: <GraduationCap className="w-4 h-4" />,
              desc: "A single UK university, in one term. Most institutions report that traditional checkers flag AI-generated work as original — integrity offices are overwhelmed by tools that miss the problem entirely.",
              tone: "danger",
            },
            {
              tag: "Peer Review",
              year: "2024",
              stat: "11,300+",
              statLabel: "papers retracted",
              icon: <FileCheck className="w-4 h-4" />,
              desc: "Publishers including Wiley and Springer Nature are publicly reporting retractions tied to AI-generated text slipping past editorial review. Reviewer tools weren&apos;t designed for modern LLM output.",
              tone: "warn",
            },
            {
              tag: "Regulation",
              year: "2026",
              stat: "EU AI Act",
              statLabel: "disclosure required",
              icon: <Gavel className="w-4 h-4" />,
              desc: "Academic institutions and publishers operating in the EU must disclose AI use and maintain audit trails. A single plagiarism percentage no longer satisfies compliance requirements.",
              tone: "accent",
            },
          ].map((c, i) => {
            const borderColor =
              c.tone === "danger"
                ? "border-l-danger"
                : c.tone === "warn"
                  ? "border-l-warn"
                  : "border-l-accent";
            const statColor =
              c.tone === "danger"
                ? "text-danger"
                : c.tone === "warn"
                  ? "text-warn"
                  : "text-accent-l";
            return (
              <div
                key={i}
                className={`bg-surface border border-border/60 border-l-4 ${borderColor} rounded-2xl p-6`}
              >
                <div className="flex items-center justify-between mb-5">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-muted">
                    <span className={statColor}>{c.icon}</span>
                    {c.tag}
                  </span>
                  <span className="text-[11px] font-mono text-muted/60">{c.year}</span>
                </div>
                <p className={`text-4xl font-bold tracking-tight ${statColor} mb-1`}>{c.stat}</p>
                <p className="text-[11px] uppercase tracking-wider text-muted mb-4">{c.statLabel}</p>
                <p className="text-[13px] text-muted leading-relaxed">{c.desc}</p>
              </div>
            );
          })}
        </div>

        {/* Comparison table — tightened */}
        <div className="bg-surface border border-border/60 rounded-2xl overflow-hidden">
          <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Where single-model tools fall short</h3>
            <AlertTriangle className="w-4 h-4 text-warn" />
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 bg-bg/40">
                <th className="text-left px-6 py-3.5 font-medium text-[11px] uppercase tracking-wider text-muted">Capability</th>
                <th className="px-6 py-3.5 font-medium text-[11px] uppercase tracking-wider text-txt text-center">PlagiarismGuard</th>
                <th className="px-6 py-3.5 font-medium text-[11px] uppercase tracking-wider text-muted text-center">Legacy Tools</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Multi-agent consensus detection", true, false],
                ["AI content detection (GPT/Claude/Gemini)", true, false],
                ["Academic database scanning", true, false],
                ["Semantic paraphrase detection", true, false],
                ["Source attribution + confidence intervals", true, false],
                ["Exportable audit trail", true, false],
                ["Built-in rewriter (7 modes)", true, false],
                ["Web content scanning", true, true],
                ["Free tier", true, true],
              ].map(([feature, us, others], i) => (
                <tr key={i} className="border-b border-border/40 last:border-0 hover:bg-bg/30 transition-colors">
                  <td className="px-6 py-3.5 text-txt/90 text-[13px]">{feature as string}</td>
                  <td className="px-6 py-3.5 text-center">
                    <Check className="w-4 h-4 text-ok inline-block" />
                  </td>
                  <td className="px-6 py-3.5 text-center">
                    {others ? <Check className="w-4 h-4 text-ok inline-block" /> : <span className="text-muted/30">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ═══ INTEGRATIONS — tight strip ═══ */}
      <section className="bg-surface/30 border-y border-border/60">
        <div className="max-w-5xl mx-auto px-4 py-20">
          <div className="text-center mb-12">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">Everywhere you write</p>
            <h2 className="text-3xl font-bold tracking-tight mb-3">Reach your text in every tool you use.</h2>
            <p className="text-muted max-w-2xl mx-auto">PlagiarismGuard isn&apos;t just a website — it&apos;s available wherever you write, share, or submit work.</p>
          </div>

          {/* Channel cards */}
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-10">
            {[
              { icon: Globe, title: "Chrome Extension", desc: "Right-click any webpage to scan instantly." },
              { icon: FileText, title: "Word Add-in", desc: "Check originality without leaving Microsoft Word." },
              { icon: BookOpen, title: "Google Workspace", desc: "Sidebar add-on for Docs — scan as you write." },
              { icon: GraduationCap, title: "LMS / LTI 1.3", desc: "Launch from Canvas, Moodle & Blackboard." },
            ].map((c, i) => (
              <div key={i} className="bg-bg border border-border/60 rounded-xl p-5">
                <c.icon className="w-5 h-5 text-accent mb-3" />
                <p className="text-sm font-semibold mb-1">{c.title}</p>
                <p className="text-xs text-muted leading-relaxed">{c.desc}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap justify-center gap-x-10 gap-y-4 text-sm text-muted pt-8 border-t border-border/60">
            {[
              { icon: <FileText className="w-4 h-4" />, label: "PDF, DOCX, TXT, LaTeX, PPTX" },
              { icon: <Globe className="w-4 h-4" />, label: "50+ Languages auto-detected" },
              { icon: <Fingerprint className="w-4 h-4" />, label: "Per-model AI fingerprinting" },
              { icon: <Download className="w-4 h-4" />, label: "PDF & DOCX Export" },
              { icon: <Plug className="w-4 h-4" />, label: "REST API & Webhooks" },
              { icon: <BookOpen className="w-4 h-4" />, label: "BibTeX Citations" },
              { icon: <Users className="w-4 h-4" />, label: "Team seats & SSO" },
              { icon: <Layers className="w-4 h-4" />, label: "Batch Upload (50 files)" },
            ].map((item, i) => (
              <div key={i} className="flex items-center gap-2">
                {item.icon}
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ SECURITY — prominent pillars ═══ */}
      <section className="max-w-4xl mx-auto px-4 py-24">
        <div className="text-center mb-12">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">Security</p>
          <h2 className="text-4xl font-bold tracking-tight">
            Your documents. Your data.
            <br />
            <span className="text-muted">Protected end-to-end.</span>
          </h2>
        </div>
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            {
              icon: <Lock className="w-5 h-5" />,
              title: "Encrypted",
              desc: "TLS 1.3 in transit. AES-256 at rest. Zero-knowledge storage architecture across all tiers.",
              meta: "TLS 1.3 · AES-256",
            },
            {
              icon: <ShieldCheck className="w-5 h-5" />,
              title: "Never used for training",
              desc: "Your content never becomes training data. Your intellectual property stays yours — always.",
              meta: "SOC 2 aligned",
            },
            {
              icon: <Users className="w-5 h-5" />,
              title: "Role-based access",
              desc: "Admin, manager, member roles with per-document permissions. SAML SSO available on Team plans.",
              meta: "RBAC · SSO-ready",
            },
          ].map((s) => (
            <div
              key={s.title}
              className="group bg-surface border border-border/60 hover:border-accent/30 rounded-2xl p-7 transition-colors"
            >
              <span className="inline-flex w-11 h-11 rounded-xl bg-bg border border-border/60 items-center justify-center text-txt mb-5 group-hover:border-accent/40 group-hover:text-accent transition-colors">
                {s.icon}
              </span>
              <h3 className="text-base font-semibold mb-2">{s.title}</h3>
              <p className="text-sm text-muted leading-relaxed mb-4">{s.desc}</p>
              <p className="text-[10px] font-mono uppercase tracking-wider text-muted/60 pt-3 border-t border-border/60">
                {s.meta}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ═══ FAQ — tightened ═══ */}
      <section className="max-w-3xl mx-auto px-4 py-24">
        <div className="text-center mb-10">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-4">FAQ</p>
          <h2 className="text-3xl font-bold tracking-tight">Questions, answered.</h2>
        </div>
        <div className="border-t border-border/60">
          {[
            { q: "How accurate is the detection?", a: "99.2% — achieved by running 5 specialized agents in parallel. Each analyzes a different dimension. The Report Agent uses confidence-weighted scoring to produce the final result." },
            { q: "What file formats are supported?", a: "PDF, DOCX, TXT, LaTeX (.tex), PPTX. You can also paste text, import from Google Docs, or batch-upload up to 50 files." },
            { q: "Can it detect AI-generated content?", a: "Yes. Our AI Detection Agent identifies GPT-4, Claude, Gemini, and LLaMA text using perplexity analysis, burstiness scoring, and statistical fingerprinting with multi-model consensus." },
            { q: "How is this different from Turnitin or Grammarly?", a: "Turnitin does plagiarism. Grammarly does grammar. We do both — plus AI detection, smart rewriting (7 modes), readability (6 scores), and research writing with real citations. One platform." },
            { q: "Is my data secure?", a: "Yes. TLS 1.3 in transit, AES-256 at rest. Never shared. Never used for training. Team plans include role-based access control." },
            { q: "Do you have an API?", a: "Yes. REST API with full feature access: analysis, batch processing, history, and report retrieval. Premium plan required. Docs at /api-docs." },
          ].map((faq, i) => (
            <details key={i} className="group border-b border-border/60">
              <summary className="flex items-center justify-between px-1 py-5 cursor-pointer text-[15px] font-medium hover:text-txt list-none">
                <span>{faq.q}</span>
                <span className="w-7 h-7 rounded-full border border-border/60 flex items-center justify-center text-muted group-hover:text-accent group-hover:border-accent/40 group-open:text-accent group-open:border-accent/40 group-open:rotate-180 transition-all shrink-0">
                  <ChevronDown className="w-3.5 h-3.5" />
                </span>
              </summary>
              <div className="px-1 pb-5"><p className="text-sm text-muted leading-relaxed">{faq.a}</p></div>
            </details>
          ))}
        </div>
      </section>

      {/* ═══ FINAL CTA — monochrome, editorial ═══ */}
      <section className="border-t border-border/60">
        <div className="max-w-3xl mx-auto px-4 py-24 text-center">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted mb-6">Get Started</p>
          <h2 className="text-5xl font-bold mb-8 tracking-tight leading-[1.05]">
            Stop guessing.
            <br />
            <span className="text-muted">Start knowing.</span>
          </h2>
          <p className="text-muted max-w-lg mx-auto mb-10 leading-relaxed">
            Five AI agents. 99.2% accuracy. Results in under 30 seconds. Free tier included —
            no credit card required.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 bg-txt hover:bg-txt/90 text-bg font-semibold rounded-full transition-colors text-sm"
            >
              Start detecting — free <ArrowRight className="w-4 h-4" />
            </Link>
            <a
              href="#demo"
              className="inline-flex items-center justify-center gap-2 px-7 py-3.5 border border-border hover:border-txt/40 text-txt font-medium rounded-full transition-colors text-sm"
            >
              Try the demo
            </a>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 mt-14 text-[11px] uppercase tracking-wider text-muted">
            <span className="flex items-center gap-1.5"><Lock className="w-3 h-3" /> Encrypted</span>
            <span className="flex items-center gap-1.5"><Shield className="w-3 h-3" /> Never used for training</span>
            <span className="flex items-center gap-1.5"><Globe className="w-3 h-3" /> 120+ countries</span>
          </div>
        </div>
      </section>

      {/* ═══ FOOTER ═══ */}
      <footer className="border-t border-border bg-surface/30">
        <div className="max-w-5xl mx-auto px-4 py-12">
          <div className="grid sm:grid-cols-4 gap-8">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-5 h-5 text-accent" />
                <span className="font-bold">PlagiarismGuard</span>
              </div>
              <p className="text-xs text-muted">Multi-agent plagiarism detection, AI analysis, writing tools, and research suite.</p>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Product</h4>
              <div className="space-y-2">
                <Link href="/pricing" className="block text-xs text-muted hover:text-txt">Pricing</Link>
                <Link href="/api-docs" className="block text-xs text-muted hover:text-txt">API Docs</Link>
                <a href="#features" className="block text-xs text-muted hover:text-txt">Features</a>
                <a href="#demo" className="block text-xs text-muted hover:text-txt">Live Demo</a>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Company</h4>
              <div className="space-y-2">
                <Link href="/about" className="block text-xs text-muted hover:text-txt">About</Link>
                <Link href="/privacy" className="block text-xs text-muted hover:text-txt">Privacy</Link>
                <Link href="/terms" className="block text-xs text-muted hover:text-txt">Terms</Link>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold mb-3">Support</h4>
              <div className="space-y-2">
                <span className="block text-xs text-muted">support@plagiarismguard.com</span>
              </div>
            </div>
          </div>
          <div className="border-t border-border mt-8 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-xs text-muted">&copy; {new Date().getFullYear()} PlagiarismGuard. All rights reserved.</p>
            <div className="flex items-center gap-4 text-xs text-muted">
              <Lock className="w-3.5 h-3.5" />
              <span>Your data is encrypted and never used for AI training.</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
