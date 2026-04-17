"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Users,
  BarChart3,
  Activity,
  DollarSign,
  ChevronLeft,
  ChevronRight,
  Shield,
} from "lucide-react";
import api from "@/lib/api";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useToastStore } from "@/lib/stores/toast-store";
import { formatDate } from "@/lib/utils";
import { Button, Badge, Spinner, Input, Modal } from "@/components/ui";
import Card from "@/components/ui/Card";
import AuthGuard from "@/components/AuthGuard";

interface Stats {
  total_users: number;
  plans: Record<string, number>;
  total_scans: number;
  total_payments: number;
  total_revenue_inr: number;
}

interface UserRow {
  id: number;
  name: string;
  email: string;
  plan_type: string;
  is_paid: boolean;
  created_at: string;
  scan_count: number;
  usage_count: number;
}

export default function AdminPage() {
  const { user } = useAuthStore();
  const toast = useToastStore();

  const [stats, setStats] = useState<Stats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [usersMeta, setUsersMeta] = useState({ total: 0, page: 1, per_page: 25, total_pages: 1 });
  const [search, setSearch] = useState("");
  const [planFilter, setPlanFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [editUser, setEditUser] = useState<UserRow | null>(null);
  const [newPlan, setNewPlan] = useState("");

  useEffect(() => {
    api
      .get("/api/v1/admin/stats")
      .then((r) => setStats(r.data))
      .catch(() => toast.add("error", "Failed to load admin stats."));
  }, [toast]);

  const fetchUsers = useCallback(
    async (page = 1) => {
      setLoading(true);
      try {
        const params: Record<string, string | number> = {
          page,
          per_page: 25,
        };
        if (search) params.search = search;
        if (planFilter !== "all") params.plan_filter = planFilter;

        const res = await api.get("/api/v1/admin/users", { params });
        setUsers(res.data.users || res.data);
        setUsersMeta({
          total: res.data.total ?? 0,
          page: res.data.page ?? page,
          per_page: res.data.per_page ?? 25,
          total_pages: res.data.total_pages ?? 1,
        });
      } catch {
        toast.add("error", "Failed to load users.");
      } finally {
        setLoading(false);
      }
    },
    [search, planFilter, toast]
  );

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const updatePlan = async () => {
    if (!editUser || !newPlan) return;
    try {
      await api.post("/api/v1/admin/update-plan", {
        user_id: editUser.id,
        plan_type: newPlan,
      });
      toast.add("success", `Plan updated to ${newPlan}.`);
      setEditUser(null);
      setNewPlan("");
      fetchUsers(usersMeta.page);
    } catch {
      toast.add("error", "Failed to update plan.");
    }
  };

  return (
    <AuthGuard>
      <div className="min-h-screen bg-bg text-txt">
        <div className="max-w-6xl mx-auto px-4 py-8">
          <div className="flex items-center gap-3 mb-8">
            <Shield className="w-6 h-6 text-accent" />
            <h1 className="text-2xl font-bold">Admin Panel</h1>
            {user && (
              <Badge variant="accent">{user.email}</Badge>
            )}
          </div>

          {/* Stats */}
          {stats && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
              <StatCard
                icon={<Users className="w-5 h-5 text-accent" />}
                label="Total Users"
                value={stats.total_users}
              />
              <StatCard
                icon={<BarChart3 className="w-5 h-5 text-ok" />}
                label="Total Scans"
                value={stats.total_scans}
              />
              <StatCard
                icon={<Activity className="w-5 h-5 text-warn" />}
                label="Payments"
                value={stats.total_payments}
              />
              <StatCard
                icon={<DollarSign className="w-5 h-5 text-danger" />}
                label="Revenue (INR)"
                value={`₹${stats.total_revenue_inr.toLocaleString()}`}
              />
            </div>
          )}

          {/* Plan breakdown */}
          {stats && (
            <div className="flex gap-3 mb-8 flex-wrap">
              {Object.entries(stats.plans).map(([plan, count]) => (
                <div
                  key={plan}
                  className="bg-surface border border-border rounded-xl px-4 py-2"
                >
                  <p className="text-xs text-muted capitalize">{plan}</p>
                  <p className="text-lg font-bold">{count}</p>
                </div>
              ))}
            </div>
          )}

          {/* Users table */}
          <Card>
            <div className="flex flex-wrap gap-3 mb-4">
              <div className="flex-1 min-w-[200px]">
                <Input
                  placeholder="Search users…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                value={planFilter}
                onChange={(e) => setPlanFilter(e.target.value)}
                className="bg-surface border border-border rounded-xl px-3 py-2 text-sm text-txt focus:outline-none focus:ring-2 focus:ring-accent/50"
              >
                <option value="all">All Plans</option>
                <option value="free">Free</option>
                <option value="pro">Pro</option>
                <option value="premium">Premium</option>
              </select>
            </div>

            {loading ? (
              <div className="flex justify-center py-12">
                <Spinner size="lg" />
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted">
                        <th className="py-2 px-3">Name</th>
                        <th className="py-2 px-3">Email</th>
                        <th className="py-2 px-3">Plan</th>
                        <th className="py-2 px-3">Scans</th>
                        <th className="py-2 px-3">Joined</th>
                        <th className="py-2 px-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr
                          key={u.id}
                          className="border-b border-border/30 hover:bg-surface2/30"
                        >
                          <td className="py-2 px-3">{u.name}</td>
                          <td className="py-2 px-3 text-muted truncate max-w-[200px]">
                            {u.email}
                          </td>
                          <td className="py-2 px-3">
                            <Badge
                              variant={
                                u.plan_type === "premium"
                                  ? "accent"
                                  : u.plan_type === "pro"
                                  ? "success"
                                  : "default"
                              }
                            >
                              {u.plan_type || "free"}
                            </Badge>
                          </td>
                          <td className="py-2 px-3 text-muted">
                            {u.scan_count}
                          </td>
                          <td className="py-2 px-3 text-muted whitespace-nowrap">
                            {formatDate(u.created_at)}
                          </td>
                          <td className="py-2 px-3">
                            <button
                              onClick={() => {
                                setEditUser(u);
                                setNewPlan(u.plan_type || "free");
                              }}
                              className="text-xs text-accent hover:underline"
                            >
                              Change Plan
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="flex items-center justify-between mt-4">
                  <span className="text-xs text-muted">
                    Page {usersMeta.page} of {usersMeta.total_pages} (
                    {usersMeta.total} users)
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={usersMeta.page <= 1}
                      onClick={() => fetchUsers(usersMeta.page - 1)}
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={usersMeta.page >= usersMeta.total_pages}
                      onClick={() => fetchUsers(usersMeta.page + 1)}
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </Card>

          {/* Change plan modal */}
          <Modal
            open={!!editUser}
            onClose={() => setEditUser(null)}
            title={`Change Plan — ${editUser?.name}`}
          >
            <p className="text-sm text-muted mb-4">
              Current plan: {editUser?.plan_type || "free"}
            </p>
            <select
              value={newPlan}
              onChange={(e) => setNewPlan(e.target.value)}
              className="w-full bg-surface border border-border rounded-xl px-3 py-2 text-sm text-txt mb-4 focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="free">Free</option>
              <option value="pro">Pro</option>
              <option value="premium">Premium</option>
            </select>
            <div className="flex gap-3 justify-end">
              <Button variant="secondary" onClick={() => setEditUser(null)}>
                Cancel
              </Button>
              <Button onClick={updatePlan}>Update Plan</Button>
            </div>
          </Modal>
        </div>
      </div>
    </AuthGuard>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-2">{icon}</div>
      <p className="text-xs text-muted">{label}</p>
      <p className="text-xl font-bold">{value}</p>
    </div>
  );
}
