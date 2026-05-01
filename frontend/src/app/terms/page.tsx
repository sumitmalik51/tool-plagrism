import Link from "next/link";
import { Shield } from "lucide-react";

export const metadata = {
  title: "Terms of Service — PlagiarismGuard",
};

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-bg text-txt">
      <nav className="border-b border-border">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center">
          <Link href="/" className="flex items-center gap-2 text-sm text-muted hover:text-txt">
            <Shield className="w-4 h-4 text-accent" /> PlagiarismGuard
          </Link>
        </div>
      </nav>
      <article className="max-w-3xl mx-auto px-4 py-16 prose-sm text-txt/80">
        <h1 className="text-3xl font-bold text-txt mb-8">Terms of Service</h1>
        <p className="text-muted mb-6">Last updated: April 2026</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">1. Acceptance</h2>
        <p className="mb-4 leading-relaxed">By using PlagiarismGuard, you agree to these terms. If you do not agree, do not use the service.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">2. Service Description</h2>
        <p className="mb-4 leading-relaxed">PlagiarismGuard provides plagiarism detection, AI content analysis, and writing assistance tools. Results are informational and should be used as one factor in content evaluation.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">3. User Responsibilities</h2>
        <p className="mb-4 leading-relaxed">You are responsible for the content you upload. Do not upload content you do not have rights to analyze. Do not use the service to facilitate academic dishonesty.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">4. Payments & Refunds</h2>
        <p className="mb-4 leading-relaxed">Paid subscriptions are billed monthly or annually. Refunds are available within 7 days of purchase if no significant usage has occurred.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">5. Limitation of Liability</h2>
        <p className="mb-4 leading-relaxed">PlagiarismGuard is provided &quot;as is&quot;. We are not liable for decisions made based on our analysis results.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">6. Changes</h2>
        <p className="mb-4 leading-relaxed">We may update these terms. Continued use after changes constitutes acceptance.</p>
      </article>
    </div>
  );
}
