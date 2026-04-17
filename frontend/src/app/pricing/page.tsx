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
    monthlyInr: 0,
    annualInr: 0,
    icon: <Zap className="w-5 h-5" />,
    features: [
      "3 scans per day",
      "5,000 word limit",
      "Basic plagiarism detection",
      "AI content detection",
      "Limited rewrite uses",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    monthlyInr: 299,
    annualInr: 2999,
    icon: <Star className="w-5 h-5" />,
    popular: true,
    features: [
      "25 scans per day",
      "25,000 word limit",
      "Advanced multi-agent detection",
      "AI content detection",
      "Batch analysis (5 files)",
      "Grammar & readability",
      "Research Writer access",
      "PDF/DOCX export",
      "Priority support",
    ],
  },
  {
    id: "premium",
    name: "Premium",
    monthlyInr: 599,
    annualInr: 5999,
    icon: <Sparkles className="w-5 h-5" />,
    features: [
      "Unlimited scans",
      "100,000 word limit",
      "Full multi-agent detection",
      "AI content detection",
      "Batch analysis (10 files)",
      "Grammar & readability",
      "Research Writer (unlimited)",
      "All export formats",
      "API access",
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

                <div className="flex items-center gap-2 mb-4 text-accent">
                  {plan.icon}
                  <h3 className="text-xl font-bold text-txt">{plan.name}</h3>
                </div>

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
