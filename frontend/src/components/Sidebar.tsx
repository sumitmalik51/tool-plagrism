"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Shield,
  Search,
  History,
  Wrench,
  PenTool,
  CreditCard,
  Settings,
  LogOut,
  Menu,
  X,
  ChevronDown,
  GitCompare,
  Highlighter,
  Layers,
  RefreshCw,
  SpellCheck,
  BookOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/lib/stores/auth-store";
import Badge from "@/components/ui/Badge";

const mainNav = [
  { href: "/dashboard", label: "Analyze", icon: Search },
  { href: "/dashboard/history", label: "History", icon: History },
];

const toolsSubNav = [
  { href: "/dashboard/tools", label: "All Tools", icon: Wrench },
  { href: "/dashboard/tools?tab=compare", label: "Compare", icon: GitCompare },
  { href: "/dashboard/tools?tab=highlight", label: "Highlight", icon: Highlighter },
  { href: "/dashboard/tools?tab=batch", label: "Batch", icon: Layers },
  { href: "/dashboard/tools?tab=rewrite", label: "Rewrite", icon: RefreshCw },
  { href: "/dashboard/tools?tab=grammar", label: "Grammar", icon: SpellCheck },
  { href: "/dashboard/tools?tab=readability", label: "Readability", icon: BookOpen },
];

const bottomNav = [
  { href: "/dashboard/research-writer", label: "Research Writer", icon: PenTool },
  { href: "/pricing", label: "Pricing", icon: CreditCard },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

function planBadgeVariant(plan: string) {
  if (plan.startsWith("premium")) return "warning" as const;
  if (plan.startsWith("pro")) return "accent" as const;
  return "default" as const;
}

export default function Sidebar() {
  const [open, setOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const pathname = usePathname();
  const { user, logout } = useAuthStore();

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href.split("?")[0]);
  };

  const navLink = (
    item: { href: string; label: string; icon: React.ElementType },
    onClick?: () => void
  ) => (
    <Link
      key={item.href}
      href={item.href}
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors",
        isActive(item.href)
          ? "bg-accent/15 text-accent-l"
          : "text-muted hover:text-txt hover:bg-surface2"
      )}
    >
      <item.icon className="w-4 h-4 shrink-0" />
      {item.label}
    </Link>
  );

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border">
        <Link href="/dashboard" className="flex items-center gap-3">
          <div className="w-9 h-9 bg-gradient-to-br from-accent to-ok rounded-xl grid place-items-center shadow-lg shadow-accent/20">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <span className="text-lg font-bold">
            Plagiarism<span className="text-accent">Guard</span>
          </span>
        </Link>
      </div>

      {/* Main nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {mainNav.map((item) => navLink(item, () => setOpen(false)))}

        {/* Tools accordion */}
        <button
          onClick={() => setToolsOpen(!toolsOpen)}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors",
            pathname.startsWith("/dashboard/tools")
              ? "bg-accent/15 text-accent-l"
              : "text-muted hover:text-txt hover:bg-surface2"
          )}
        >
          <Wrench className="w-4 h-4 shrink-0" />
          Tools
          <ChevronDown
            className={cn(
              "w-4 h-4 ml-auto transition-transform",
              toolsOpen && "rotate-180"
            )}
          />
        </button>
        {toolsOpen && (
          <div className="ml-4 space-y-0.5">
            {toolsSubNav.map((item) => navLink(item, () => setOpen(false)))}
          </div>
        )}

        <div className="my-3 border-t border-border" />

        {bottomNav.map((item) => navLink(item, () => setOpen(false)))}
      </nav>

      {/* User footer */}
      <div className="px-3 py-4 border-t border-border">
        <div className="flex items-center gap-3 px-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-accent/20 grid place-items-center text-accent-l text-sm font-bold shrink-0">
            {user?.name?.charAt(0)?.toUpperCase() || "?"}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-txt truncate">
              {user?.name || "User"}
            </p>
            <Badge variant={planBadgeVariant(user?.plan_type || "free")}>
              {(user?.plan_type || "free").replace("_", " ")}
            </Badge>
          </div>
        </div>
        <button
          onClick={() => {
            logout();
            window.location.href = "/login";
          }}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-muted hover:text-danger hover:bg-danger/10 transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sign Out
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setOpen(true)}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-surface border border-border rounded-xl text-muted hover:text-txt transition-colors"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile overlay */}
      {open && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Mobile sidebar */}
      <aside
        className={cn(
          "lg:hidden fixed inset-y-0 left-0 z-50 w-64 bg-surface border-r border-border transition-transform duration-300",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <button
          onClick={() => setOpen(false)}
          className="absolute top-4 right-4 text-muted hover:text-txt"
        >
          <X className="w-5 h-5" />
        </button>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:flex-col lg:fixed lg:inset-y-0 bg-surface border-r border-border">
        {sidebarContent}
      </aside>
    </>
  );
}
