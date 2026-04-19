"use client";

import { useEffect, useRef, useState } from "react";
import Script from "next/script";
import { Loader2 } from "lucide-react";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useToastStore } from "@/lib/stores/toast-store";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            auto_select?: boolean;
            ux_mode?: "popup" | "redirect";
            use_fedcm_for_prompt?: boolean;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              type?: "standard" | "icon";
              theme?: "outline" | "filled_blue" | "filled_black";
              size?: "large" | "medium" | "small";
              text?: "signin_with" | "signup_with" | "continue_with" | "signin";
              shape?: "rectangular" | "pill" | "circle" | "square";
              logo_alignment?: "left" | "center";
              width?: number | string;
            }
          ) => void;
          prompt: (
            momentListener?: (notification: {
              isNotDisplayed: () => boolean;
              isSkippedMoment: () => boolean;
              isDismissedMoment: () => boolean;
              getNotDisplayedReason: () => string;
              getSkippedReason: () => string;
              getDismissedReason: () => string;
            }) => void
          ) => void;
          disableAutoSelect: () => void;
          cancel: () => void;
        };
      };
    };
  }
}

interface GoogleSignInButtonProps {
  /** Button label variant */
  text?: "signin_with" | "signup_with" | "continue_with";
  /** Optional referral code to pass through on signup */
  referralCode?: string;
  /** Where to navigate after successful auth */
  onSuccess?: () => void;
}

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

type GsiTheme = "outline" | "filled_blue" | "filled_black";

function readSiteTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "dark";
  const t = document.documentElement.getAttribute("data-theme");
  return t === "light" ? "light" : "dark";
}

export default function GoogleSignInButton({
  text = "continue_with",
  referralCode,
  onSuccess,
}: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scriptReady, setScriptReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [siteTheme, setSiteTheme] = useState<"light" | "dark">("dark");
  const { googleLogin } = useAuthStore();
  const toast = useToastStore();

  // Track site theme via the data-theme attribute on <html>.
  useEffect(() => {
    setSiteTheme(readSiteTheme());
    const html = document.documentElement;
    const obs = new MutationObserver(() => setSiteTheme(readSiteTheme()));
    obs.observe(html, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  // Keep latest callback deps in refs so the init effect runs only once.
  const googleLoginRef = useRef(googleLogin);
  const onSuccessRef = useRef(onSuccess);
  const referralCodeRef = useRef(referralCode);
  const toastRef = useRef(toast);
  useEffect(() => {
    googleLoginRef.current = googleLogin;
    onSuccessRef.current = onSuccess;
    referralCodeRef.current = referralCode;
    toastRef.current = toast;
  });

  useEffect(() => {
    if (!scriptReady || !CLIENT_ID || !containerRef.current || !window.google) return;

    // Module-level guard so init runs only once even with HMR / multiple mounts.
    const w = window as unknown as { __pgGsiInitialized?: string };
    if (w.__pgGsiInitialized !== CLIENT_ID) {
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (response) => {
          if (!response.credential) return;
          setBusy(true);
          setError("");
          try {
            await googleLoginRef.current(response.credential, referralCodeRef.current);
            toastRef.current.add("success", "Signed in with Google");
            onSuccessRef.current?.();
          } catch (err: unknown) {
            const msg =
              (err as { response?: { data?: { detail?: string } } })?.response?.data
                ?.detail || "Google sign-in failed. Please try again.";
            setError(msg);
          } finally {
            // Always clear the spinner so the user isn't stuck on "Signing you in…"
            // even if route navigation is slow (webpack dev compile, etc.).
            setBusy(false);
          }
        },
        ux_mode: "popup",
      });
      w.__pgGsiInitialized = CLIENT_ID;
    }

    const gsiTheme: GsiTheme = siteTheme === "light" ? "outline" : "filled_black";

    containerRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(containerRef.current, {
      type: "standard",
      theme: gsiTheme,
      size: "large",
      text,
      shape: "pill",
      logo_alignment: "center",
      width: containerRef.current.offsetWidth || 360,
    });
  }, [scriptReady, text, siteTheme]);

  if (!CLIENT_ID) {
    // Hide entirely if not configured — don't show a broken button.
    return null;
  }

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
        onLoad={() => setScriptReady(true)}
      />
      <div className="space-y-2">
        <div className="relative">
          <div
            ref={containerRef}
            className={`w-full flex justify-center min-h-[44px] transition-opacity ${
              busy ? "opacity-0 pointer-events-none" : "opacity-100"
            }`}
          />
          {busy && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 rounded-full border border-border bg-surface">
              <Loader2 className="w-4 h-4 animate-spin text-accent" />
              <span className="text-sm font-medium text-txt">
                Signing you in with Google…
              </span>
            </div>
          )}
        </div>
        {error && (
          <p className="text-xs text-danger text-center">{error}</p>
        )}
      </div>
    </>
  );
}
