import Link from "next/link";
import { Shield, Users, Target, Sparkles } from "lucide-react";

export const metadata = {
  title: "About — PlagiarismGuard",
};

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-bg text-txt">
      <nav className="border-b border-border">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center">
          <Link href="/" className="flex items-center gap-2 text-sm text-muted hover:text-txt">
            <Shield className="w-4 h-4 text-accent" /> PlagiarismGuard
          </Link>
        </div>
      </nav>
      <div className="max-w-3xl mx-auto px-4 py-16">
        <h1 className="text-3xl font-bold mb-8">About PlagiarismGuard</h1>

        <p className="text-txt/80 text-lg leading-relaxed mb-12">
          PlagiarismGuard is an AI-powered platform that helps students,
          researchers, and institutions verify the originality of their work.
          Our multi-agent detection system combines web search, academic
          database matching, and AI content analysis for comprehensive results.
        </p>

        <div className="grid sm:grid-cols-3 gap-6 mb-16">
          <div className="bg-surface border border-border rounded-2xl p-6 text-center">
            <Target className="w-8 h-8 text-accent mx-auto mb-3" />
            <h3 className="font-semibold mb-2">Our Mission</h3>
            <p className="text-sm text-muted">
              Promote academic integrity through accessible, accurate detection
              tools.
            </p>
          </div>
          <div className="bg-surface border border-border rounded-2xl p-6 text-center">
            <Sparkles className="w-8 h-8 text-accent mx-auto mb-3" />
            <h3 className="font-semibold mb-2">Technology</h3>
            <p className="text-sm text-muted">
              Multi-agent AI architecture combining 6 specialized agents for
              comprehensive analysis.
            </p>
          </div>
          <div className="bg-surface border border-border rounded-2xl p-6 text-center">
            <Users className="w-8 h-8 text-accent mx-auto mb-3" />
            <h3 className="font-semibold mb-2">Community</h3>
            <p className="text-sm text-muted">
              Trusted by 50,000+ users across universities and research
              institutions worldwide.
            </p>
          </div>
        </div>

        <div className="text-center">
          <Link
            href="/signup"
            className="inline-flex items-center gap-2 px-6 py-3 bg-accent hover:bg-accent/90 text-white font-medium rounded-xl transition-colors"
          >
            Get Started Free
          </Link>
        </div>
      </div>
    </div>
  );
}
