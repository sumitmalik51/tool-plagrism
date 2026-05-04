"use client";

import { useState, useEffect } from "react";
import { Settings, User, BarChart3, Key, Gift, Plug, Users } from "lucide-react";
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

interface ApiKeyData {
  id: number;
  prefix: string;
  name: string;
  is_active: boolean;
  created_at: string;
  last_used_at?: string | null;
}

interface WebhookData {
  id: number;
  url: string;
  events: string[];
  is_active: boolean;
  created_at: string;
}

interface WebhookDeliveryData {
  id: number;
  url: string;
  event: string;
  status: string;
  attempts: number;
  response_code?: number | null;
  last_error?: string | null;
  created_at: string;
}

export default function SettingsPage() {
  const { user } = useAuthStore();
  const toast = useToastStore();
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [referral, setReferral] = useState<ReferralData | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKeyData[]>([]);
  const [newKey, setNewKey] = useState("");
  const [keyName, setKeyName] = useState("Default");
  const [webhooks, setWebhooks] = useState<WebhookData[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryData[]>([]);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get("/api/v1/auth/usage").then((r) => setUsage(r.data)),
      api.get("/api/v1/auth/referral").then((r) => setReferral(r.data)).catch(() => {}),
      api.get("/api/v1/auth/api-keys").then((r) => setApiKeys(r.data.keys || [])).catch(() => {}),
      api.get("/api/v1/webhooks").then((r) => setWebhooks(r.data.webhooks || [])).catch(() => {}),
      api.get("/api/v1/webhooks/deliveries").then((r) => setDeliveries(r.data.deliveries || [])).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const copyReferral = () => {
    if (!referral?.referral_code) return;
    const url = `${window.location.origin}/signup?ref=${referral.referral_code}`;
    navigator.clipboard.writeText(url);
    toast.add("success", "Referral link copied!");
  };

  const createApiKey = async () => {
    try {
      const r = await api.post("/api/v1/auth/api-keys", { name: keyName || "Default" });
      setNewKey(r.data.key);
      const list = await api.get("/api/v1/auth/api-keys");
      setApiKeys(list.data.keys || []);
      toast.add("success", "API key created. Copy it now — it is shown once.");
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.add("error", msg || "Could not create API key.");
    }
  };

  const createWebhook = async () => {
    if (!webhookUrl.trim()) return;
    try {
      await api.post("/api/v1/webhooks", { url: webhookUrl.trim(), events: ["scan.complete"] });
      setWebhookUrl("");
      const list = await api.get("/api/v1/webhooks");
      setWebhooks(list.data.webhooks || []);
      toast.add("success", "Webhook registered.");
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.add("error", msg || "Could not register webhook.");
    }
  };

  const regenerateApiKey = async (keyId: number) => {
    try {
      const r = await api.post("/api/v1/auth/api-keys/regenerate", { key_id: keyId });
      setNewKey(r.data.key);
      const list = await api.get("/api/v1/auth/api-keys");
      setApiKeys(list.data.keys || []);
      toast.add("success", "API key rotated. Copy the new secret now.");
    } catch {
      toast.add("error", "Could not rotate API key.");
    }
  };

  const deleteApiKey = async (keyId: number) => {
    try {
      await api.delete(`/api/v1/auth/api-keys/${keyId}`);
      setApiKeys((keys) => keys.filter((key) => key.id !== keyId));
      toast.add("success", "API key deleted.");
    } catch {
      toast.add("error", "Could not delete API key.");
    }
  };

  const deleteWebhook = async (webhookId: number) => {
    try {
      await api.delete(`/api/v1/webhooks/${webhookId}`);
      setWebhooks((items) => items.map((item) => item.id === webhookId ? { ...item, is_active: false } : item));
      toast.add("success", "Webhook disabled.");
    } catch {
      toast.add("error", "Could not disable webhook.");
    }
  };

  const replayDelivery = async (deliveryId: number) => {
    try {
      await api.post(`/api/v1/webhooks/deliveries/${deliveryId}/replay`);
      const list = await api.get("/api/v1/webhooks/deliveries");
      setDeliveries(list.data.deliveries || []);
      toast.add("success", "Webhook replay queued.");
    } catch {
      toast.add("error", "Could not replay webhook delivery.");
    }
  };

  const wordLimit = typeof usage?.word_quota.limit === "number" ? usage.word_quota.limit : 0;
  const wordUsed = usage?.word_quota.used ?? 0;
  const wordRemaining = typeof usage?.word_quota.remaining === "number" ? usage.word_quota.remaining : -1;
  const topupRemaining = usage?.word_quota.topup_remaining ?? 0;
  const wordPct = wordLimit > 0 ? Math.min((wordUsed / wordLimit) * 100, 100) : 0;

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
                {wordLimit > 0 ? wordLimit.toLocaleString() : "unlimited"}
              </p>
            </div>
          </div>
          {/* Word quota bar */}
          <div className="mt-4">
            <div className="h-2 bg-surface2 rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all"
                style={{
                  width: `${wordPct}%`,
                }}
              />
            </div>
            <p className="text-xs text-muted mt-1">
              {wordRemaining === -1 ? "Unlimited" : wordRemaining.toLocaleString()} words available
              {topupRemaining > 0 ? ` · ${topupRemaining.toLocaleString()} top-up words` : ""}
              {usage.word_quota.resets_at ? ` · resets ${new Date(usage.word_quota.resets_at).toLocaleDateString()}` : ""}
            </p>
            {wordLimit > 0 && wordPct >= 70 && (
              <a href="/pricing" className="inline-block mt-3 text-xs text-accent-l hover:text-accent">
                {wordPct >= 90 ? "Quota almost used — upgrade or buy top-up →" : "Plan ahead: view quota top-ups →"}
              </a>
            )}
          </div>
        </Card>
      )}

      {/* Developer portal */}
      <Card>
        <div className="flex items-center gap-4 mb-4">
          <Plug className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-semibold">Webhook / API Developer Portal</h2>
        </div>
        {newKey && (
          <div className="mb-4 p-3 bg-ok/10 border border-ok/30 rounded-xl">
            <p className="text-xs text-ok mb-1">New key — copy now</p>
            <code className="block text-xs break-all">{newKey}</code>
          </div>
        )}
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Key className="w-4 h-4 text-muted" />
              <h3 className="text-sm font-semibold">API Keys</h3>
            </div>
            <div className="flex gap-2 mb-3">
              <input
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm"
                placeholder="Key name"
              />
              <button onClick={createApiKey} className="px-3 py-2 bg-accent text-white rounded-lg text-sm">
                Create
              </button>
            </div>
            <div className="space-y-2">
              {apiKeys.length === 0 ? (
                <p className="text-xs text-muted">No keys yet. Pro/Premium required.</p>
              ) : apiKeys.map((k) => (
                <div key={k.id} className="p-2 bg-bg rounded-lg border border-border text-xs">
                  <div className="flex justify-between gap-2"><span className="font-medium">{k.name}</span><span>{k.is_active ? "active" : "revoked"}</span></div>
                  <code className="text-muted">{k.prefix}</code>
                  {k.is_active && (
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => regenerateApiKey(k.id)} className="text-accent-l hover:text-accent">
                        Rotate
                      </button>
                      <button onClick={() => deleteApiKey(k.id)} className="text-danger hover:text-danger/80">
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold mb-2">Webhooks</h3>
            <div className="flex gap-2 mb-3">
              <input
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm"
                placeholder="https://example.com/scan-complete"
              />
              <button onClick={createWebhook} className="px-3 py-2 bg-accent text-white rounded-lg text-sm">
                Add
              </button>
            </div>
            <div className="space-y-2">
              {webhooks.length === 0 ? (
                <p className="text-xs text-muted">No webhooks registered.</p>
              ) : webhooks.map((w) => (
                <div key={w.id} className="p-2 bg-bg rounded-lg border border-border text-xs">
                  <p className="truncate font-medium">{w.url}</p>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-muted">{w.events.join(", ")} · {w.is_active ? "active" : "inactive"}</p>
                    {w.is_active && (
                      <button onClick={() => deleteWebhook(w.id)} className="text-danger hover:text-danger/80">
                        Disable
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-border">
          <h3 className="text-sm font-semibold mb-2">Recent webhook deliveries</h3>
          {deliveries.length === 0 ? (
            <p className="text-xs text-muted">Delivery audit appears here after scans complete.</p>
          ) : (
            <div className="space-y-2">
              {deliveries.slice(0, 5).map((d) => (
                <div key={d.id} className="flex items-center justify-between gap-3 text-xs bg-bg border border-border rounded-lg p-2">
                  <span className="truncate">{d.event} → {d.url}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={d.status === "delivered" ? "text-ok" : d.status === "blocked" ? "text-warn" : "text-danger"}>
                      {d.status} ({d.attempts})
                    </span>
                    {d.status !== "blocked" && (
                      <button onClick={() => replayDelivery(d.id)} className="text-accent-l hover:text-accent">
                        Replay
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <a href="/api-docs" className="inline-block mt-3 text-xs text-accent-l hover:text-accent">
            View API docs and webhook signing guide →
          </a>
        </div>
      </Card>

      {/* Team workspace */}
      <Card>
        <div className="flex items-center gap-4 mb-4">
          <Users className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-semibold">Institution / Team Workspace</h2>
          <Badge variant="warning">Coming soon</Badge>
        </div>
        <p className="text-sm text-muted mb-3">
          Shared seats, team quota pools, SSO, LMS rollout, and organization-level reports are opening for early partners.
        </p>
        <a href="mailto:sales@plagiarismguard.com?subject=Immediate%20Team%20Workspace%20Access" className="text-sm text-accent-l hover:text-accent">
          Reach out to get immediate access →
        </a>
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
