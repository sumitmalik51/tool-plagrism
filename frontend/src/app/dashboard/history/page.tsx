"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  Download,
  Trash2,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  BarChart3,
  List,
} from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import { formatDate, scoreColor } from "@/lib/utils";

function riskVariant(risk: string): "success" | "warning" | "danger" {
  switch (risk.toUpperCase()) {
    case "LOW": return "success";
    case "MEDIUM": return "warning";
    default: return "danger";
  }
}
import { Button, Badge, Spinner, Modal, Input } from "@/components/ui";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

interface ScanRow {
  id: number;
  document_id: string;
  plagiarism_score: number;
  confidence_score: number;
  risk_level: string;
  sources_count: number;
  flagged_count: number;
  created_at: string;
  filename?: string;
  file_type?: string;
}

interface ChartData {
  score_trend: { score: number; confidence: number; risk: string; date: string }[];
  risk_distribution: Record<string, number>;
  daily_counts: { date: string; count: number }[];
}

const LIMIT = 20;
const PIE_COLORS = ["#00b894", "#fdcb6e", "#e17055"];

export default function HistoryPage() {
  const router = useRouter();
  const toast = useToastStore();

  const [scans, setScans] = useState<ScanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [sortBy, setSortBy] = useState("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [view, setView] = useState<"list" | "charts">("list");
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const fetchScans = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        limit: LIMIT,
        offset,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (search) params.search = search;
      if (riskFilter) params.risk_level = riskFilter;

      const res = await api.get("/api/v1/auth/scans", { params });
      const data = res.data.scans as ScanRow[];
      setScans(data);
      setHasMore(data.length === LIMIT);
    } catch {
      toast.add("error", "Failed to load scan history.");
    } finally {
      setLoading(false);
    }
  }, [offset, sortBy, sortOrder, search, riskFilter, toast]);

  useEffect(() => {
    fetchScans();
  }, [fetchScans]);

  const fetchCharts = useCallback(async () => {
    setChartLoading(true);
    try {
      const res = await api.get("/api/v1/auth/scans/chart-data");
      setChartData(res.data);
    } catch {
      toast.add("error", "Failed to load chart data.");
    } finally {
      setChartLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (view === "charts" && !chartData) fetchCharts();
  }, [view, chartData, fetchCharts]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.delete(`/api/v1/auth/scans/${deleteTarget}`);
      toast.add("success", "Scan deleted.");
      setDeleteTarget(null);
      fetchScans();
    } catch {
      toast.add("error", "Failed to delete scan.");
    }
  };

  const exportCsv = async () => {
    try {
      const res = await api.get("/api/v1/auth/scans/export-csv", {
        responseType: "blob",
      });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = "plagiarismguard-scans.csv";
      a.click();
      URL.revokeObjectURL(url);
      toast.add("success", "CSV exported!");
    } catch {
      toast.add("error", "Failed to export CSV.");
    }
  };

  const toggleSort = (col: string) => {
    if (sortBy === col) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortOrder("desc");
    }
    setOffset(0);
  };

  const page = Math.floor(offset / LIMIT) + 1;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Scan History</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setView("list")}
            className={`p-2 rounded-lg transition-colors ${
              view === "list"
                ? "bg-accent text-white"
                : "bg-surface2 text-muted hover:text-txt"
            }`}
          >
            <List className="w-4 h-4" />
          </button>
          <button
            onClick={() => setView("charts")}
            className={`p-2 rounded-lg transition-colors ${
              view === "charts"
                ? "bg-accent text-white"
                : "bg-surface2 text-muted hover:text-txt"
            }`}
          >
            <BarChart3 className="w-4 h-4" />
          </button>
          <Button variant="secondary" onClick={exportCsv}>
            <Download className="w-4 h-4 mr-1" />
            Export CSV
          </Button>
        </div>
      </div>

      {view === "list" ? (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <div className="flex-1 min-w-[200px]">
              <Input
                placeholder="Search by filename or ID…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
              />
            </div>
            <select
              value={riskFilter}
              onChange={(e) => {
                setRiskFilter(e.target.value);
                setOffset(0);
              }}
              className="bg-surface border border-border rounded-xl px-3 py-2 text-sm text-txt focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="">All Risk Levels</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
            </select>
          </div>

          {/* Table */}
          {loading ? (
            <div className="flex justify-center py-16">
              <Spinner size="lg" />
            </div>
          ) : scans.length === 0 ? (
            <div className="text-center py-16 text-muted">
              <Search className="w-10 h-10 mx-auto mb-3 opacity-40" />
              <p>No scans found.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-muted text-left">
                    <SortHeader
                      label="Date"
                      col="created_at"
                      sortBy={sortBy}
                      sortOrder={sortOrder}
                      onSort={toggleSort}
                    />
                    <th className="py-3 px-3">Filename</th>
                    <SortHeader
                      label="Score"
                      col="plagiarism_score"
                      sortBy={sortBy}
                      sortOrder={sortOrder}
                      onSort={toggleSort}
                    />
                    <SortHeader
                      label="Risk"
                      col="risk_level"
                      sortBy={sortBy}
                      sortOrder={sortOrder}
                      onSort={toggleSort}
                    />
                    <SortHeader
                      label="Sources"
                      col="sources_count"
                      sortBy={sortBy}
                      sortOrder={sortOrder}
                      onSort={toggleSort}
                    />
                    <th className="py-3 px-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.map((s) => (
                    <tr
                      key={s.document_id}
                      className="border-b border-border/50 hover:bg-surface2/50 cursor-pointer transition-colors"
                      onClick={() =>
                        router.push(`/dashboard/history/${s.document_id}`)
                      }
                    >
                      <td className="py-3 px-3 whitespace-nowrap text-muted">
                        {formatDate(s.created_at)}
                      </td>
                      <td className="py-3 px-3 max-w-[200px] truncate">
                        {s.filename || s.document_id.slice(0, 12) + "…"}
                      </td>
                      <td
                        className={`py-3 px-3 font-semibold ${scoreColor(
                          s.plagiarism_score
                        )}`}
                      >
                        {(s.plagiarism_score ?? 0).toFixed(1)}%
                      </td>
                      <td className="py-3 px-3">
                        <Badge variant={riskVariant(s.risk_level)}>
                          {s.risk_level}
                        </Badge>
                      </td>
                      <td className="py-3 px-3 text-muted">
                        {s.sources_count}
                      </td>
                      <td className="py-3 px-3">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTarget(s.document_id);
                          }}
                          className="text-muted hover:text-danger transition-colors"
                          title="Delete scan"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted">Page {page}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!hasMore}
                onClick={() => setOffset((o) => o + LIMIT)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </>
      ) : (
        /* Charts view */
        <div className="space-y-6">
          {chartLoading ? (
            <div className="flex justify-center py-16">
              <Spinner size="lg" />
            </div>
          ) : !chartData ? null : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Score trend */}
              <div className="bg-surface border border-border rounded-2xl p-6">
                <h3 className="text-sm font-semibold text-muted mb-4">
                  Score Trend (last 30 scans)
                </h3>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={chartData.score_trend}>
                    <CartesianGrid stroke="#2e3348" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) =>
                        new Date(v).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })
                      }
                      tick={{ fill: "#8b8fa3", fontSize: 11 }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fill: "#8b8fa3", fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1a1d27",
                        border: "1px solid #2e3348",
                        borderRadius: 12,
                        color: "#e1e4ed",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="score"
                      stroke="#e17055"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      name="Plagiarism %"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Risk distribution */}
              <div className="bg-surface border border-border rounded-2xl p-6">
                <h3 className="text-sm font-semibold text-muted mb-4">
                  Risk Distribution
                </h3>
                <ResponsiveContainer width="100%" height={250}>
                  <PieChart>
                    <Pie
                      data={Object.entries(chartData.risk_distribution).map(
                        ([name, value]) => ({ name, value })
                      )}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      dataKey="value"
                      label={({ name, value }: { name?: string; value?: number }) =>
                        `${name ?? ""}: ${value ?? 0}`
                      }
                    >
                      {Object.keys(chartData.risk_distribution).map((_, i) => (
                        <Cell
                          key={i}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1a1d27",
                        border: "1px solid #2e3348",
                        borderRadius: 12,
                        color: "#e1e4ed",
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              {/* Daily scan counts */}
              <div className="bg-surface border border-border rounded-2xl p-6 lg:col-span-2">
                <h3 className="text-sm font-semibold text-muted mb-4">
                  Daily Scans (last 30 days)
                </h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={chartData.daily_counts}>
                    <CartesianGrid stroke="#2e3348" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) =>
                        new Date(v).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                        })
                      }
                      tick={{ fill: "#8b8fa3", fontSize: 11 }}
                    />
                    <YAxis
                      tick={{ fill: "#8b8fa3", fontSize: 11 }}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1a1d27",
                        border: "1px solid #2e3348",
                        borderRadius: 12,
                        color: "#e1e4ed",
                      }}
                    />
                    <Bar
                      dataKey="count"
                      fill="#6c5ce7"
                      radius={[6, 6, 0, 0]}
                      name="Scans"
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Delete confirmation modal */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Scan"
      >
        <p className="text-sm text-muted mb-4">
          Are you sure? This action cannot be undone.
        </p>
        <div className="flex gap-3 justify-end">
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDelete}>
            Delete
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function SortHeader({
  label,
  col,
  sortBy,
  sortOrder,
  onSort,
}: {
  label: string;
  col: string;
  sortBy: string;
  sortOrder: string;
  onSort: (col: string) => void;
}) {
  return (
    <th
      className="py-3 px-3 cursor-pointer select-none hover:text-txt transition-colors"
      onClick={() => onSort(col)}
    >
      <span className="flex items-center gap-1">
        {label}
        <ArrowUpDown
          className={`w-3 h-3 ${
            sortBy === col ? "text-accent" : "text-muted/40"
          } ${sortBy === col && sortOrder === "asc" ? "rotate-180" : ""}`}
        />
      </span>
    </th>
  );
}
