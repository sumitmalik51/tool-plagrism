"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Shield, CheckCircle, XCircle } from "lucide-react";
import api from "@/lib/api";
import Spinner from "@/components/ui/Spinner";

type Status = "loading" | "success" | "error";

function VerifyEmailContent() {
  const [status, setStatus] = useState<Status>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  useEffect(() => {
    if (!token) return;

    api
      .post("/api/v1/auth/verify-email", { token })
      .then(() => {
        setStatus("success");
      })
      .catch((err) => {
        const msg =
          err?.response?.data?.detail || "Verification failed. The link may have expired.";
        setErrorMessage(msg);
        setStatus("error");
      });
  }, [token]);

  const effectiveStatus = !token ? "error" : status;
  const effectiveMessage = !token ? "No verification token provided." : errorMessage;

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-3">
            <div className="w-11 h-11 bg-gradient-to-br from-accent to-ok rounded-xl grid place-items-center shadow-lg shadow-accent/20">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <span className="text-xl font-bold">
              Plagiarism<span className="text-accent">Guard</span>
            </span>
          </Link>
        </div>

        {/* Card */}
        <div className="bg-surface border border-border rounded-2xl p-8 text-center">
          {effectiveStatus === "loading" && (
            <div className="py-8">
              <Spinner size="lg" className="mx-auto mb-4" />
              <p className="text-muted">Verifying your email…</p>
            </div>
          )}

          {effectiveStatus === "success" && (
            <div className="py-8">
              <CheckCircle className="w-16 h-16 text-ok mx-auto mb-4" />
              <h1 className="text-2xl font-bold mb-2">Email Verified!</h1>
              <p className="text-muted mb-6">
                Your email has been confirmed. You can now sign in.
              </p>
              <Link
                href="/login"
                className="inline-flex items-center px-6 py-3 bg-accent hover:bg-accent/80 text-white rounded-xl font-medium transition-colors shadow-lg shadow-accent/20"
              >
                Sign In →
              </Link>
            </div>
          )}

          {effectiveStatus === "error" && (
            <div className="py-8">
              <XCircle className="w-16 h-16 text-danger mx-auto mb-4" />
              <h1 className="text-2xl font-bold mb-2">Verification Failed</h1>
              <p className="text-muted mb-6">{effectiveMessage}</p>
              <Link
                href="/login"
                className="inline-flex items-center px-6 py-3 bg-surface2 hover:bg-border text-txt rounded-xl font-medium transition-colors border border-border"
              >
                Go to Login
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}
