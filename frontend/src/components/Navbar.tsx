"use client";

import { useAuthStore } from "@/lib/stores/auth-store";
import Badge from "@/components/ui/Badge";
import ThemeToggle from "@/components/ThemeToggle";

export default function Navbar() {
  const { user } = useAuthStore();

  return (
    <header className="sticky top-0 z-30 bg-bg/80 backdrop-blur-xl border-b border-border/50">
      <div className="flex items-center justify-between px-4 sm:px-6 lg:px-8 h-14">
        {/* Left spacer for mobile hamburger */}
        <div className="w-8 lg:hidden" />

        {/* Page context - empty for now, pages can use portal */}
        <div className="flex-1" />

        {/* Right side */}
        <div className="flex items-center gap-3">
          <ThemeToggle />
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
          <div className="w-8 h-8 rounded-full bg-accent/20 grid place-items-center text-accent-l text-sm font-bold">
            {user?.name?.charAt(0)?.toUpperCase() || "?"}
          </div>
        </div>
      </div>
    </header>
  );
}
