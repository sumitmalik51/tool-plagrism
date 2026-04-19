"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Shield, Eye, EyeOff, Gift } from "lucide-react";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useToastStore } from "@/lib/stores/toast-store";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import GoogleSignInButton from "@/components/GoogleSignInButton";

function SignupContent() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [referralCode, setReferralCode] = useState("");

  const { signup } = useAuthStore();
  const toast = useToastStore();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const ref = searchParams.get("ref");
    if (ref) setReferralCode(ref);
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);

    try {
      await signup({
        name,
        email,
        password,
        referral_code: referralCode || undefined,
      });
      toast.add("success", "Account created! Welcome to PlagiarismGuard.");
      router.push("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Could not create account. Please try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4 py-8">
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
          {/* Tabs */}
          <div className="grid grid-cols-2 gap-1 p-1 mb-6 bg-bg border border-border rounded-xl">
            <Link
              href="/login"
              className="px-4 py-2 rounded-lg text-sm font-medium text-muted hover:text-txt text-center transition-colors"
            >
              Sign in
            </Link>
            <button
              type="button"
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-surface text-txt shadow-sm"
              aria-current="page"
            >
              Join free
            </button>
          </div>

          <h1 className="text-2xl font-bold text-center mb-2">
            Create your account
          </h1>
          <p className="text-muted text-center text-sm mb-4">
            Start checking your work for free
          </p>

          {/* Trial badge */}
          <div className="mb-6 p-3 bg-accent/10 border border-accent/20 rounded-xl text-center">
            <span className="text-sm text-accent-l">
              🎉 3-day Research trial included — no credit card required
            </span>
          </div>

          {/* Referral badge */}
          {referralCode && (
            <div className="mb-4 p-3 bg-ok/10 border border-ok/20 rounded-xl flex items-center gap-2 justify-center">
              <Gift className="w-4 h-4 text-ok" />
              <span className="text-sm text-ok">
                Referral bonus: 5 free scans on signup!
              </span>
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-danger/10 border border-danger/20 rounded-xl text-danger text-sm">
              {error}
            </div>
          )}

          {/* Google sign-up */}
          <GoogleSignInButton
            text="signup_with"
            referralCode={referralCode || undefined}
            onSuccess={() => router.push("/dashboard")}
          />

          <div className="my-5 flex items-center gap-3">
            <div className="flex-1 h-px bg-border" />
            <span className="text-xs uppercase tracking-wider text-muted">or</span>
            <div className="flex-1 h-px bg-border" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              id="name"
              label="Full Name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="John Doe"
              autoComplete="name"
              required
            />

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

            <div className="relative">
              <Input
                id="password"
                label="Password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
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
                confirmPassword && password !== confirmPassword
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
              Create Account
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function SignupPage() {
  return (
    <Suspense>
      <SignupContent />
    </Suspense>
  );
}
