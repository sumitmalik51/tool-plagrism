"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
            itp_support?: boolean;
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

const LABELS: Record<NonNullable<GoogleSignInButtonProps["text"]>, string> = {
  signin_with: "Sign in with Google",
  signup_with: "Sign up with Google",
  continue_with: "Continue with Google",
};

/** Official multi-color Google "G" mark (allowed for use on custom buttons). */
function GoogleGIcon({ className = "w-[18px] h-[18px]" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        fill="#FFC107"
        d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z"
      />
      <path
        fill="#FF3D00"
        d="M6.306 14.691l6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238C29.211 35.091 26.715 36 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.611 20.083H42V20H24v8h11.303c-.792 2.237-2.231 4.166-4.087 5.571.001-.001.002-.001.003-.002l6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z"
      />
    </svg>
  );
}

export default function GoogleSignInButton({
  text = "continue_with",
  referralCode,
  onSuccess,
}: GoogleSignInButtonProps) {
  const hiddenContainerRef = useRef<HTMLDivElement>(null);
  const [scriptReady, setScriptReady] = useState(false);
  const [gsiReady, setGsiReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { googleLogin } = useAuthStore();
  const toast = useToastStore();

  // Keep latest deps in refs so init runs only once.
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

  // Initialise GSI + render the official button (hidden off-screen) once.
  useEffect(() => {
    if (!scriptReady || !CLIENT_ID || !window.google || !hiddenContainerRef.current) return;

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
            setBusy(false);
          }
        },
        ux_mode: "popup",
        itp_support: true,
        auto_select: false,
      });
      w.__pgGsiInitialized = CLIENT_ID;
    }

    // Render the official Google button into a hidden container. We forward our
    // custom button's clicks to it so the user sees a native Google popup
    // (the only flow that reliably returns an id_token credential JWT).
    hiddenContainerRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(hiddenContainerRef.current, {
      type: "standard",
      theme: "outline",
      size: "large",
      text: "continue_with",
      shape: "rectangular",
      logo_alignment: "left",
      width: 320,
    });
    setGsiReady(true);
  }, [scriptReady]);

  const handleClick = useCallback(() => {
    if (!gsiReady || !hiddenContainerRef.current) return;
    setError("");
    // The rendered GSI button is wrapped in a div > div[role=button]. Click
    // it programmatically so Google opens its popup with our credentials.
    const realBtn =
      hiddenContainerRef.current.querySelector<HTMLElement>("div[role=button]") ||
      hiddenContainerRef.current.querySelector<HTMLElement>("[role=button]") ||
      (hiddenContainerRef.current.firstElementChild as HTMLElement | null);
    if (realBtn) {
      realBtn.click();
    } else {
      setError("Google sign-in is still loading. Please try again in a moment.");
    }
  }, [gsiReady]);

  if (!CLIENT_ID) {
    // Hide entirely if not configured — don't show a broken button.
    return null;
  }

  const label = LABELS[text];
  const disabled = !gsiReady || busy;

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
        onLoad={() => setScriptReady(true)}
      />
      <div className="space-y-2">
        <button
          type="button"
          onClick={handleClick}
          disabled={disabled}
          aria-label={label}
          className="w-full flex items-center justify-center gap-3 h-11 px-4 rounded-xl border border-border bg-surface2 text-sm font-medium text-txt transition-colors hover:bg-border focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-accent" />
              <span>Signing you in with Google…</span>
            </>
          ) : (
            <>
              <GoogleGIcon />
              <span>{label}</span>
            </>
          )}
        </button>
        {/*
          Hidden GSI-rendered button. Kept off-screen but interactive so we can
          forward our custom button's clicks to it. Using `position: fixed` +
          negative offset (rather than display:none / visibility:hidden) because
          Google's library refuses to open the popup if the button isn't
          considered visible by the browser.
        */}
        <div
          aria-hidden="true"
          style={{
            position: "fixed",
            top: "-1000px",
            left: "-1000px",
            width: "320px",
            height: "44px",
            opacity: 0,
            pointerEvents: "none",
            overflow: "hidden",
          }}
        >
          <div ref={hiddenContainerRef} />
        </div>
        {error && <p className="text-xs text-danger text-center">{error}</p>}
      </div>
    </>
  );
}
