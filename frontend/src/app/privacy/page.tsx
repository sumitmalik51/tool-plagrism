import Link from "next/link";
import { Shield } from "lucide-react";

export const metadata = {
  title: "Privacy Policy — PlagiarismGuard",
};

export default function PrivacyPage() {
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
        <h1 className="text-3xl font-bold text-txt mb-8">Privacy Policy</h1>
        <p className="text-muted mb-6">Last updated: April 2025</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">1. Information We Collect</h2>
        <p className="mb-4 leading-relaxed">We collect information you provide when creating an account (name, email), documents you upload for analysis, and usage data to improve our service.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">2. How We Use Your Information</h2>
        <p className="mb-4 leading-relaxed">Your documents are analyzed for plagiarism detection only. We do not sell, share, or use your content for training AI models. Analysis results are stored in your account for your reference.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">3. Data Security</h2>
        <p className="mb-4 leading-relaxed">All data is encrypted in transit (TLS 1.3) and at rest. Access to user data is restricted to authorized personnel only.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">4. Data Retention</h2>
        <p className="mb-4 leading-relaxed">Uploaded documents and scan results are retained in your account until you delete them. Account data is retained for the duration of your account plus 30 days after deletion.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">5. Cookies</h2>
        <p className="mb-4 leading-relaxed">We use essential cookies for authentication. No third-party tracking cookies are used.</p>

        <h2 className="text-xl font-semibold text-txt mt-8 mb-3">6. Contact</h2>
        <p className="mb-4 leading-relaxed">For privacy concerns, contact us at support@plagiarismguard.com.</p>
      </article>
    </div>
  );
}
