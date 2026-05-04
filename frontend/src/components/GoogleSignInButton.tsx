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
    __pgGsiInitialized?: string;
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

export default function GoogleSignInButton({
  text = "continue_with",
  referralCode,
  onSuccess,
}: GoogleSignInButtonProps) {
  const buttonContainerRef = useRef<HTMLDivElement>(null);
  const [scriptReady, setScriptReady] = useState(false);
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

  // Initialise GSI + render the official Google button. We render the real
  // button (not a custom one that forwards clicks) because newer GSI versions
  // render the button inside a cross-origin iframe — programmatic forwarding
  // is impossible. The official button still respects the surrounding theme
  // reasonably well at full width.
  useEffect(() => {
    if (!scriptReady || !CLIENT_ID || !window.google || !buttonContainerRef.current) return;

    if (window.__pgGsiInitialized !== CLIENT_ID) {
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
      window.__pgGsiInitialized = CLIENT_ID;
    }

    buttonContainerRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(buttonContainerRef.current, {
      type: "standard",
      theme: "outline",
      size: "large",
      text,
      shape: "rectangular",
      logo_alignment: "center",
      width: 400,
    });
  }, [scriptReady, text]);

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
        <div
          className="relative h-11 w-full flex items-center justify-center rounded-xl border border-border bg-surface2 overflow-hidden"
          aria-busy={busy}
        >
          {/* The official GSI button renders inside an iframe. We size the
              container to match the rest of the form (full-width, h-11) and
              center the iframe inside it. */}
          <div
            ref={buttonContainerRef}
            className="[&>div]:!w-full [&_iframe]:!w-full"
            style={{ width: "100%", display: busy ? "none" : "flex", justifyContent: "center" }}
          />
          {busy && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-muted bg-surface2">
              <Loader2 className="w-4 h-4 animate-spin text-accent" />
              <span>Signing you in with Google…</span>
            </div>
          )}
        </div>
        {error && <p className="text-xs text-danger text-center">{error}</p>}
      </div>
    </>
  );
}
