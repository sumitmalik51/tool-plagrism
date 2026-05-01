"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Check, Sparkles, Star, Zap } from "lucide-react";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useToastStore } from "@/lib/stores/toast-store";
import { Button, Badge } from "@/components/ui";

/* ─── Currency ──────────────────────────────────────────── */

type Currency = "INR" | "USD" | "EUR" | "GBP";
const CURRENCY_SYMBOLS: Record<Currency, string> = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
};
const RATES: Record<Currency, number> = {
  INR: 1,
  USD: 0.012,
  EUR: 0.011,
  GBP: 0.0095,
};

/* ─── Plans ─────────────────────────────────────────────── */

const PLANS = [
  {
    id: "free",
    name: "Free",
    tagline: "Try the full engine",
    monthlyInr: 0,
    annualInr: 0,
    icon: <Zap className="w-5 h-5" />,
    features: [
      "3 scans per day",
      "5,000 words / month",
      "All 5 detection agents",
      "AI content + per-model fingerprinting",
      "PDF, DOCX, TXT, PPTX, LaTeX uploads",
      "Google Docs import",
      "Chrome extension",
      "50+ languages",
      "1 trial of each Research Writer tool",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    tagline: "For serious writers & researchers",
    monthlyInr: 299,
    annualInr: 2999,
    icon: <Star className="w-5 h-5" />,
    popular: true,
    features: [
      "25 scans per day",
      "200,000 words / month",
      "All Free features, plus:",
      "Batch analysis (5 files)",
      "50 MB per file upload",
      "Grammar, readability & 7-mode rewriter",
      "Research Writer (25 generations / day)",
      "Compare, highlight & share reports",
      "PDF / DOCX report export",
      "5 API keys",
      "Priority support",
    ],
  },
  {
    id: "premium",
    name: "Premium",
    tagline: "Power users & small teams",
    monthlyInr: 599,
    annualInr: 5999,
    icon: <Sparkles className="w-5 h-5" />,
    features: [
      "Unlimited scans",
      "500,000 words / month",
      "All Pro features, plus:",
      "Batch analysis (10 files)",
      "100 MB per file upload",
      "Deeper web search (15 queries / scan)",
      "Research Writer (75 generations + unlimited check/expand/improve)",
      "Webhooks for scan events",
      "20 API keys",
      "Repository check & cross-compare",
      "Dedicated support",
    ],
  },
];

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => {
      open: () => void;
    };
  }
}

export default function PricingPage() {
  const router = useRouter();
  const toast = useToastStore();
  const { isAuthenticated, user, fetchUser } = useAuthStore();

  const [annual, setAnnual] = useState(true);
  const [currency, setCurrency] = useState<Currency>("INR");
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);

  const price = (inr: number) => {
    const converted = inr * RATES[currency];
    return converted < 1 && converted > 0
      ? converted.toFixed(2)
      : Math.round(converted).toLocaleString();
  };

  const sym = CURRENCY_SYMBOLS[currency];

  const loadRazorpayScript = useCallback(() => {
    if (document.getElementById("razorpay-sdk")) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const s = document.createElement("script");
      s.id = "razorpay-sdk";
      s.src = "https://checkout.razorpay.com/v1/checkout.js";
      s.onload = () => resolve();
      document.body.appendChild(s);
    });
  }, []);

  const subscribe = async (planId: string) => {
    if (!isAuthenticated) {
      router.push("/login?redirect=/pricing");
      return;
    }
    if (planId === "free") return;

    setLoadingPlan(planId);
    try {
      const orderPlanId = annual ? `${planId}_annual` : planId;
      const res = await api.post("/api/v1/auth/create-order", {
        plan: orderPlanId,
      });
      const { order_id, amount, razorpay_key, user_name, user_email } =
        res.data;

      await loadRazorpayScript();

      const options = {
        key: razorpay_key,
        amount,
        currency: "INR",
        name: "PlagiarismGuard",
        description: `${planId.charAt(0).toUpperCase() + planId.slice(1)} Plan`,
        order_id,
        prefill: { name: user_name, email: user_email },
        theme: { color: "#6c5ce7" },
        handler: async (response: {
          razorpay_order_id: string;
          razorpay_payment_id: string;
          razorpay_signature: string;
        }) => {
          try {
            await api.post("/api/v1/auth/verify-payment", {
              ...response,
              plan: orderPlanId,
            });
            toast.add("success", "Payment successful! Plan upgraded.");
            fetchUser();
            router.push("/dashboard");
          } catch {
            toast.add("error", "Payment verification failed.");
          }
        },
        modal: {
          ondismiss: () => setLoadingPlan(null),
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch {
      toast.add("error", "Failed to create order.");
    } finally {
      setLoadingPlan(null);
    }
  };

  return (
    <div className="min-h-screen bg-bg text-txt">
      <div className="max-w-5xl mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-3">
            Simple, Transparent Pricing
          </h1>
          <p className="text-muted text-lg">
            Choose the plan that fits your needs
          </p>
        </div>

        {/* Controls */}
        <div className="flex justify-center gap-6 mb-10 flex-wrap">
          {/* Billing toggle */}
          <div className="flex items-center gap-3 bg-surface border border-border rounded-xl p-1">
            <button
              onClick={() => setAnnual(false)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                !annual
                  ? "bg-accent text-white"
                  : "text-muted hover:text-txt"
              }`}
            >
              Monthly
            </button>
            <button
              onClick={() => setAnnual(true)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                annual
                  ? "bg-accent text-white"
                  : "text-muted hover:text-txt"
              }`}
            >
              Annual
              <Badge variant="success" className="ml-2">
                Save 16%
              </Badge>
            </button>
          </div>

          {/* Currency picker */}
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value as Currency)}
            className="bg-surface border border-border rounded-xl px-4 py-2 text-sm text-txt focus:outline-none focus:ring-2 focus:ring-accent/50"
          >
            {(Object.keys(CURRENCY_SYMBOLS) as Currency[]).map((c) => (
              <option key={c} value={c}>
                {CURRENCY_SYMBOLS[c]} {c}
              </option>
            ))}
          </select>
        </div>

        {/* Plan cards */}
        <div className="grid md:grid-cols-3 gap-6">
          {PLANS.map((plan) => {
            const displayPrice = annual && plan.annualInr > 0
              ? price(plan.annualInr / 12)
              : price(plan.monthlyInr);
            const isCurrentPlan =
              user?.plan_type === plan.id ||
              (plan.id === "free" && !user?.plan_type);

            return (
              <div
                key={plan.id}
                className={`relative bg-surface border rounded-2xl p-6 flex flex-col ${
                  plan.popular
                    ? "border-accent shadow-lg shadow-accent/10"
                    : "border-border"
                }`}
              >
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge variant="accent">Most Popular</Badge>
                  </div>
                )}

                <div className="flex items-center gap-2 mb-1 text-accent">
                  {plan.icon}
                  <h3 className="text-xl font-bold text-txt">{plan.name}</h3>
                </div>
                <p className="text-xs text-muted mb-4">{plan.tagline}</p>

                <div className="mb-6">
                  {plan.monthlyInr === 0 ? (
                    <span className="text-3xl font-bold">Free</span>
                  ) : (
                    <>
                      <span className="text-3xl font-bold">
                        {sym}
                        {displayPrice}
                      </span>
                      <span className="text-muted text-sm">/month</span>
                      {annual && (
                        <p className="text-xs text-muted mt-1">
                          Billed {sym}
                          {price(plan.annualInr)}/year
                        </p>
                      )}
                    </>
                  )}
                </div>

                <ul className="space-y-3 flex-1 mb-6">
                  {plan.features.map((f, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-sm text-txt/80"
                    >
                      <Check className="w-4 h-4 text-ok shrink-0 mt-0.5" />
                      {f}
                    </li>
                  ))}
                </ul>

                {isCurrentPlan ? (
                  <Button variant="secondary" disabled className="w-full">
                    Current Plan
                  </Button>
                ) : plan.id === "free" ? (
                  <Button
                    variant="secondary"
                    className="w-full"
                    onClick={() => router.push("/signup")}
                  >
                    Get Started
                  </Button>
                ) : (
                  <Button
                    variant={plan.popular ? "primary" : "secondary"}
                    className="w-full"
                    loading={loadingPlan === plan.id}
                    onClick={() => subscribe(plan.id)}
                  >
                    {isAuthenticated ? "Upgrade" : "Get Started"}
                  </Button>
                )}
              </div>
            );
          })}
        </div>

        {/* Full feature comparison */}
        <div className="mt-20">
          <h2 className="text-2xl font-bold text-center mb-2">
            Compare every feature
          </h2>
          <p className="text-sm text-muted text-center mb-8">
            All plans include our 5-agent detection engine — the limits scale up.
          </p>
          <div className="overflow-x-auto bg-surface border border-border rounded-2xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-bg/40">
                  <th className="text-left font-medium text-muted px-5 py-4">Feature</th>
                  <th className="text-center font-semibold px-5 py-4">Free</th>
                  <th className="text-center font-semibold px-5 py-4 text-accent-l">Pro</th>
                  <th className="text-center font-semibold px-5 py-4">Premium</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[
                  { f: "Scans per day", free: "3", pro: "25", prem: "Unlimited" },
                  { f: "Word quota / month", free: "5,000", pro: "200,000", prem: "500,000" },
                  { f: "Max file size", free: "5 MB", pro: "50 MB", prem: "100 MB" },
                  { f: "5 detection agents", free: "✓", pro: "✓", prem: "✓" },
                  { f: "AI model fingerprinting (GPT/Claude/Gemini)", free: "✓", pro: "✓", prem: "✓" },
                  { f: "PDF, DOCX, TXT, PPTX, LaTeX", free: "✓", pro: "✓", prem: "✓" },
                  { f: "Google Docs import", free: "✓", pro: "✓", prem: "✓" },
                  { f: "Chrome extension", free: "✓", pro: "✓", prem: "✓" },
                  { f: "50+ language support", free: "✓", pro: "✓", prem: "✓" },
                  { f: "Batch analysis", free: "—", pro: "5 files", prem: "10 files" },
                  { f: "Grammar & readability", free: "—", pro: "✓", prem: "✓" },
                  { f: "7-mode AI rewriter", free: "Trial", pro: "✓", prem: "✓" },
                  { f: "Research Writer", free: "1 trial each", pro: "25 / day", prem: "75 / day + unlimited check / expand / improve" },
                  { f: "Compare scans", free: "—", pro: "✓", prem: "✓" },
                  { f: "Highlight diff", free: "—", pro: "✓", prem: "✓" },
                  { f: "Share reports", free: "—", pro: "✓", prem: "✓" },
                  { f: "PDF / DOCX report export", free: "—", pro: "✓", prem: "✓" },
                  { f: "Repository check & cross-compare", free: "—", pro: "—", prem: "✓" },
                  { f: "Web search depth", free: "Standard", pro: "Standard", prem: "Deep (15 queries)" },
                  { f: "API keys", free: "—", pro: "5", prem: "20" },
                  { f: "Webhooks", free: "—", pro: "—", prem: "✓" },
                  { f: "Word add-in & Google Workspace add-on", free: "✓", pro: "✓", prem: "✓" },
                  { f: "Support", free: "Community", pro: "Priority", prem: "Dedicated" },
                ].map((row, i) => (
                  <tr key={i} className="hover:bg-bg/30">
                    <td className="px-5 py-3 text-txt/85">{row.f}</td>
                    <td className="px-5 py-3 text-center text-muted">{row.free}</td>
                    <td className="px-5 py-3 text-center font-medium">{row.pro}</td>
                    <td className="px-5 py-3 text-center text-muted">{row.prem}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Teams / Enterprise CTA */}
        <div className="mt-12 bg-gradient-to-br from-accent/10 to-transparent border border-accent/30 rounded-2xl p-8 text-center">
          <h3 className="text-xl font-bold mb-2">Need a team plan or LMS integration?</h3>
          <p className="text-sm text-muted mb-5 max-w-xl mx-auto">
            Seat-based teams, LTI 1.3 launch from Canvas / Moodle / Blackboard, SSO, custom rate limits, and on-premise deployment.
          </p>
          <a
            href="mailto:sales@plagiarismguard.com"
            className="inline-flex items-center gap-2 px-6 py-3 bg-txt text-bg font-semibold rounded-full text-sm hover:bg-txt/90 transition-colors"
          >
            Talk to sales
          </a>
        </div>

        {/* FAQ */}
        <div className="mt-16">
          <h2 className="text-2xl font-bold text-center mb-8">
            Frequently asked questions
          </h2>
          <div className="grid md:grid-cols-2 gap-6">
            {[
              {
                q: "What happens if I hit my word quota?",
                a: "Scans are paused until your quota resets at the start of the next month, or you can buy a top-up credit pack or upgrade your plan instantly.",
              },
              {
                q: "Can I cancel any time?",
                a: "Yes. Cancel from Settings — you keep access until the end of your billing period and never get auto-charged again.",
              },
              {
                q: "Is my content stored or used for training?",
                a: "No. Documents are processed and the report is saved to your private history. We never use your text to train any model.",
              },
              {
                q: "Do you accept international cards?",
                a: "Yes — Razorpay handles INR, and we accept Stripe for international USD / EUR / GBP cards.",
              },
              {
                q: "What's the difference between Pro and Premium?",
                a: "Pro is sized for individual writers (200K words, 25 scans/day). Premium adds unlimited scans, deeper web search, repository check, webhooks, and more API keys for power users.",
              },
              {
                q: "Refund policy?",
                a: "7-day money-back guarantee on the first month of any paid plan, no questions asked.",
              },
            ].map((item, i) => (
              <div
                key={i}
                className="bg-surface border border-border rounded-xl p-5"
              >
                <p className="font-semibold mb-2 text-sm">{item.q}</p>
                <p className="text-sm text-muted leading-relaxed">{item.a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Back link */}
        <div className="text-center mt-12">
          <button
            onClick={() => router.push(isAuthenticated ? "/dashboard" : "/")}
            className="text-sm text-muted hover:text-txt transition-colors"
          >
            ← Back to {isAuthenticated ? "Dashboard" : "Home"}
          </button>
        </div>
      </div>
    </div>
  );
}
