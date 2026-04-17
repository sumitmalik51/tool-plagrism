"use client";

import { useState, useEffect } from "react";
import { Settings, User, BarChart3, Key, Gift } from "lucide-react";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useToastStore } from "@/lib/stores/toast-store";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Spinner from "@/components/ui/Spinner";
import type { UsageResponse } from "@/lib/types";

interface ReferralData {
  referral_code: string;
  bonus_scans: number;
  referral_count: number;
}

export default function SettingsPage() {
  const { user } = useAuthStore();
  const toast = useToastStore();
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [referral, setReferral] = useState<ReferralData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get("/api/v1/auth/usage").then((r) => setUsage(r.data)),
      api.get("/api/v1/auth/referral").then((r) => setReferral(r.data)).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const copyReferral = () => {
    if (!referral?.referral_code) return;
    const url = `${window.location.origin}/signup?ref=${referral.referral_code}`;
    navigator.clipboard.writeText(url);
    toast.add("success", "Referral link copied!");
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3 mb-2">
        <Settings className="w-6 h-6 text-accent" />
        <h1 className="text-2xl font-bold">Settings</h1>
      </div>

      {/* Profile */}
      <Card>
        <div className="flex items-center gap-4 mb-4">
          <User className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-semibold">Profile</h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-muted mb-1">Name</p>
            <p className="text-sm font-medium">{user?.name || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted mb-1">Email</p>
            <p className="text-sm font-medium">{user?.email || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted mb-1">Plan</p>
            <Badge
              variant={
                user?.plan_type?.startsWith("premium")
                  ? "warning"
                  : user?.plan_type?.startsWith("pro")
                  ? "accent"
                  : "default"
              }
            >
              {(user?.plan_type || "free").replace("_", " ")}
            </Badge>
          </div>
          {user?.trial_ends_at && (
            <div>
              <p className="text-xs text-muted mb-1">Trial Ends</p>
              <p className="text-sm font-medium">
                {new Date(user.trial_ends_at).toLocaleDateString()}
              </p>
            </div>
          )}
        </div>
      </Card>

      {/* Usage */}
      {usage && (
        <Card>
          <div className="flex items-center gap-4 mb-4">
            <BarChart3 className="w-5 h-5 text-muted" />
            <h2 className="text-lg font-semibold">Usage</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-muted mb-1">Scans Today</p>
              <p className="text-sm font-medium">
                {usage.used_today} / {usage.limit}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Remaining Today</p>
              <p className="text-sm font-medium">{usage.remaining}</p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Word Quota (Monthly)</p>
              <p className="text-sm font-medium">
                {usage.word_quota.used.toLocaleString()} /{" "}
                {usage.word_quota.limit.toLocaleString()}
              </p>
            </div>
          </div>
          {/* Word quota bar */}
          <div className="mt-4">
            <div className="h-2 bg-surface2 rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all"
                style={{
                  width: `${Math.min(
                    (usage.word_quota.used / Math.max(usage.word_quota.limit, 1)) * 100,
                    100
                  )}%`,
                }}
              />
            </div>
            <p className="text-xs text-muted mt-1">
              {usage.word_quota.remaining.toLocaleString()} words remaining
            </p>
          </div>
        </Card>
      )}

      {/* API Keys */}
      <Card>
        <div className="flex items-center gap-4 mb-4">
          <Key className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-semibold">API Keys</h2>
        </div>
        <p className="text-sm text-muted">
          API key management is available on Pro and Premium plans.
          Visit the{" "}
          <a href="/api-docs" className="text-accent-l hover:text-accent">
            API docs
          </a>{" "}
          for integration details.
        </p>
      </Card>

      {/* Referral */}
      {referral && (
        <Card>
          <div className="flex items-center gap-4 mb-4">
            <Gift className="w-5 h-5 text-muted" />
            <h2 className="text-lg font-semibold">Referral Program</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div>
              <p className="text-xs text-muted mb-1">Your Code</p>
              <p className="text-sm font-mono font-medium">
                {referral.referral_code}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Referrals</p>
              <p className="text-sm font-medium">{referral.referral_count}</p>
            </div>
            <div>
              <p className="text-xs text-muted mb-1">Bonus Scans Earned</p>
              <p className="text-sm font-medium">{referral.bonus_scans}</p>
            </div>
          </div>
          <button
            onClick={copyReferral}
            className="text-sm text-accent-l hover:text-accent transition-colors"
          >
            📋 Copy referral link
          </button>
        </Card>
      )}
    </div>
  );
}
