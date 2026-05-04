import Link from "next/link";
import { Shield, Code } from "lucide-react";

export const metadata = {
  title: "API Documentation — PlagiarismGuard",
};

const ENDPOINTS = [
  {
    method: "POST",
    path: "/api/v1/analyze-agent",
    desc: "Analyze text for plagiarism using the multi-agent system.",
    body: '{ "text": "your text here" }',
  },
  {
    method: "POST",
    path: "/api/v1/analyze",
    desc: "Analyze an uploaded file (multipart/form-data).",
    body: "file: UploadFile",
  },
  {
    method: "GET",
    path: "/api/v1/auth/scans",
    desc: "List your scan history with pagination.",
    body: "?limit=20&offset=0",
  },
  {
    method: "GET",
    path: "/api/v1/export-pdf/{doc_id}",
    desc: "Download a PDF report for a scan.",
    body: "—",
  },
  {
    method: "POST",
    path: "/api/v1/share-report",
    desc: "Create a time-limited share link for a completed report.",
    body: '{ "document_id": "doc_...", "expires_in_days": 7 }',
  },
  {
    method: "POST",
    path: "/api/v1/report-certificate/{doc_id}",
    desc: "Create or return a public verification certificate for a report.",
    body: "—",
  },
  {
    method: "GET",
    path: "/api/v1/verify-report/{verification_id}",
    desc: "Publicly verify a report certificate hash and score.",
    body: "—",
  },
  {
    method: "POST",
    path: "/api/v1/auth/create-word-topup-order",
    desc: "Create a Razorpay order for an extra 100,000 scan words.",
    body: "—",
  },
  {
    method: "POST",
    path: "/api/v1/rewrite/general",
    desc: "Rewrite text with mode, tone, and strength controls.",
    body: '{ "text": "...", "mode": "paraphrase", "tone": "neutral", "strength": "medium" }',
  },
  {
    method: "POST",
    path: "/api/v1/grammar/check",
    desc: "Check text for grammar errors.",
    body: '{ "text": "your text here" }',
  },
  {
    method: "POST",
    path: "/api/v1/readability",
    desc: "Analyze text readability with Flesch-Kincaid and other scores.",
    body: '{ "text": "your text here" }',
  },
  {
    method: "POST",
    path: "/api/v1/research-writer/generate",
    desc: "Generate an academic paragraph from a graph image.",
    body: "multipart/form-data (image + explanation)",
  },
  {
    method: "GET",
    path: "/api/v1/webhooks/deliveries",
    desc: "List recent webhook delivery attempts for audit and troubleshooting.",
    body: "?limit=20",
  },
  {
    method: "POST",
    path: "/api/v1/webhooks/deliveries/{delivery_id}/replay",
    desc: "Replay a failed or delivered webhook payload to its original URL.",
    body: "—",
  },
];

export default function ApiDocsPage() {
  return (
    <div className="min-h-screen bg-bg text-txt">
      <nav className="border-b border-border">
        <div className="max-w-4xl mx-auto px-4 h-14 flex items-center">
          <Link href="/" className="flex items-center gap-2 text-sm text-muted hover:text-txt">
            <Shield className="w-4 h-4 text-accent" /> PlagiarismGuard
          </Link>
        </div>
      </nav>
      <div className="max-w-4xl mx-auto px-4 py-16">
        <div className="flex items-center gap-3 mb-8">
          <Code className="w-6 h-6 text-accent" />
          <h1 className="text-3xl font-bold">API Documentation</h1>
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6 mb-8">
          <h2 className="text-lg font-semibold mb-3">Authentication</h2>
          <p className="text-sm text-muted mb-3">
            All API requests require a Bearer token in the Authorization header.
          </p>
          <code className="text-xs bg-bg px-3 py-2 rounded-lg block text-accent-l">
            Authorization: Bearer YOUR_API_TOKEN
          </code>
          <p className="text-xs text-muted mt-3">
            Get your API token from{" "}
            <Link href="/dashboard/settings" className="text-accent hover:underline">
              Settings
            </Link>
            . API access requires a Pro or Premium plan.
          </p>
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6 mb-8">
          <h2 className="text-lg font-semibold mb-3">Base URL</h2>
          <code className="text-xs bg-bg px-3 py-2 rounded-lg block text-accent-l">
            https://your-domain.com/api/v1
          </code>
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6 mb-8">
          <h2 className="text-lg font-semibold mb-3">Webhooks</h2>
          <p className="text-sm text-muted mb-3">
            Register webhooks from Settings to receive scan completion events. Each delivery is retried and stored for audit/replay.
          </p>
          <div className="grid md:grid-cols-2 gap-3 text-xs">
            <code className="bg-bg px-3 py-2 rounded-lg block text-accent-l">
              X-PlagiarismGuard-Signature: sha256=&lt;hmac&gt;
            </code>
            <code className="bg-bg px-3 py-2 rounded-lg block text-accent-l">
              X-PlagiarismGuard-Event: scan.complete
            </code>
          </div>
          <p className="text-xs text-muted mt-3">
            Verify the signature with HMAC-SHA256 over the raw JSON body using your webhook secret.
          </p>
        </div>

        <h2 className="text-xl font-semibold mb-4">Endpoints</h2>
        <div className="space-y-4">
          {ENDPOINTS.map((ep, i) => (
            <div
              key={i}
              className="bg-surface border border-border rounded-2xl p-5"
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded ${
                    ep.method === "GET"
                      ? "bg-ok/15 text-ok"
                      : "bg-accent/15 text-accent-l"
                  }`}
                >
                  {ep.method}
                </span>
                <code className="text-sm text-txt">{ep.path}</code>
              </div>
              <p className="text-sm text-muted mb-2">{ep.desc}</p>
              <code className="text-xs bg-bg px-3 py-1.5 rounded-lg block text-muted">
                {ep.body}
              </code>
            </div>
          ))}
        </div>

        <p className="text-sm text-muted mt-8 text-center">
          For full API documentation with response schemas, contact{" "}
          <span className="text-accent-l">support@plagiarismguard.com</span>
        </p>
      </div>
    </div>
  );
}
