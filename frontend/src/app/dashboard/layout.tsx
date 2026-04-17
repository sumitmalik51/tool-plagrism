"use client";

import { useEffect } from "react";
import { useAuthStore } from "@/lib/stores/auth-store";
import AuthGuard from "@/components/AuthGuard";
import Sidebar from "@/components/Sidebar";
import Navbar from "@/components/Navbar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { loadFromStorage } = useAuthStore();

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return (
    <AuthGuard>
      <div className="min-h-screen bg-bg">
        <Sidebar />
        <div className="lg:pl-64 flex flex-col min-h-screen">
          <Navbar />
          <main className="flex-1 p-4 sm:p-6 lg:p-8">{children}</main>
        </div>
      </div>
    </AuthGuard>
  );
}
