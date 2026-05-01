"use client";

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Shield, Eye, EyeOff } from "lucide-react";
import api from "@/lib/api";
import { useToastStore } from "@/lib/stores/toast-store";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";

function ForgotPasswordContent() {
  const [step, setStep] = useState<"request" | "reset">("request");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const toast = useToastStore();
  const searchParams = useSearchParams();

  useEffect(() => {
    const urlToken = searchParams.get("token");
    if (urlToken) {
      setToken(urlToken);
      setStep("reset");
    }
  }, [searchParams]);

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    try {
      const { data } = await api.post("/api/v1/auth/forgot-password", {
        email,
      });
      setMessage(
        data.message || "If an account exists with that email, a reset link has been sent."
      );
      toast.add("success", "Check your email for reset instructions.");
    } catch {
      // Always show success message to prevent email enumeration
      setMessage(
        "If an account exists with that email, a reset link has been sent."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);

    try {
      await api.post("/api/v1/auth/reset-password", {
        token,
        new_password: newPassword,
      });
      setMessage("Password reset successfully!");
      toast.add("success", "Password reset! You can now sign in.");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Reset failed. The link may have expired.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

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
        <div className="bg-surface border border-border rounded-2xl p-8">
          {step === "request" ? (
            <>
              <h1 className="text-2xl font-bold text-center mb-2">
                Reset Password
              </h1>
              <p className="text-muted text-center text-sm mb-6">
                Enter your email and we&apos;ll send you a reset link
              </p>

              {message && (
                <div className="mb-4 p-3 bg-ok/10 border border-ok/20 rounded-xl text-ok text-sm">
                  {message}
                </div>
              )}

              {error && (
                <div className="mb-4 p-3 bg-danger/10 border border-danger/20 rounded-xl text-danger text-sm">
                  {error}
                </div>
              )}

              <form onSubmit={handleRequestReset} className="space-y-4">
                <Input
                  id="email"
                  label="Email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  required
                />

                <Button
                  type="submit"
                  loading={loading}
                  className="w-full"
                  size="lg"
                >
                  Send Reset Link
                </Button>
              </form>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-center mb-2">
                Set New Password
              </h1>
              <p className="text-muted text-center text-sm mb-6">
                Choose a strong password for your account
              </p>

              {message && (
                <div className="mb-4 p-3 bg-ok/10 border border-ok/20 rounded-xl text-ok text-sm text-center">
                  {message}{" "}
                  <Link
                    href="/login"
                    className="font-medium underline hover:text-ok"
                  >
                    Sign in now →
                  </Link>
                </div>
              )}

              {error && (
                <div className="mb-4 p-3 bg-danger/10 border border-danger/20 rounded-xl text-danger text-sm">
                  {error}
                </div>
              )}

              {!message && (
                <form onSubmit={handleResetPassword} className="space-y-4">
                  <div className="relative">
                    <Input
                      id="newPassword"
                      label="New Password"
                      type={showPassword ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="At least 8 characters"
                      autoComplete="new-password"
                      minLength={8}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-[38px] text-muted hover:text-txt transition-colors"
                      tabIndex={-1}
                    >
                      {showPassword ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>

                  <Input
                    id="confirmPassword"
                    label="Confirm Password"
                    type={showPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                    autoComplete="new-password"
                    minLength={8}
                    required
                    error={
                      confirmPassword && newPassword !== confirmPassword
                        ? "Passwords do not match"
                        : undefined
                    }
                  />

                  <Button
                    type="submit"
                    loading={loading}
                    className="w-full"
                    size="lg"
                  >
                    Reset Password
                  </Button>
                </form>
              )}
            </>
          )}
        </div>

        <p className="text-center text-sm text-muted mt-6">
          <Link
            href="/login"
            className="text-accent-l hover:text-accent font-medium transition-colors"
          >
            ← Back to Sign In
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function ForgotPasswordPage() {
  return (
    <Suspense>
      <ForgotPasswordContent />
    </Suspense>
  );
}
