"use client";

/**
 * Themeable tooltip primitive built on Radix Tooltip.
 *
 * Replaces native ``title=""`` attributes everywhere we want:
 *   - keyboard focus support
 *   - dark-mode-aware styling
 *   - rich content (icons, links) instead of plain strings
 *   - consistent timing across the app
 *
 * Usage:
 *
 *   <Tooltip content="Confidence in this score">
 *     <button>?</button>
 *   </Tooltip>
 *
 * For arbitrary JSX content, pass it as children of ``content``:
 *
 *   <Tooltip content={<>Multi-line<br/>tooltip body</>}>
 *     <span tabIndex={0}>info</span>
 *   </Tooltip>
 */

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface TooltipProps {
  /** The element that triggers the tooltip on hover/focus. */
  children: ReactNode;
  /** Tooltip body — string or JSX. ``null``/empty hides the tooltip entirely. */
  content: ReactNode;
  /** Show side. Defaults to ``top``. */
  side?: "top" | "right" | "bottom" | "left";
  /** Hover delay in ms before opening. Defaults to 200. */
  delayDuration?: number;
  /** Optional className applied to the popover content. */
  className?: string;
  /** Keep the trigger as the original DOM node instead of wrapping in a span. */
  asChild?: boolean;
}

/**
 * Single, app-wide ``TooltipProvider`` should be mounted near the root.
 * Mount it once in your layout: ``<TooltipProvider>{children}</TooltipProvider>``.
 * Individual ``Tooltip`` instances do not need their own provider.
 */
export const TooltipProvider = TooltipPrimitive.Provider;

export default function Tooltip({
  children,
  content,
  side = "top",
  delayDuration = 200,
  className,
  asChild = true,
}: TooltipProps) {
  // Empty/null content: render trigger only — keeps callsites tidy when the
  // tooltip text is conditional.
  if (content == null || content === "") {
    return <>{children}</>;
  }

  return (
    <TooltipPrimitive.Root delayDuration={delayDuration}>
      <TooltipPrimitive.Trigger asChild={asChild}>
        {children}
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-xs rounded-md border border-border bg-surface px-2.5 py-1.5",
            "text-xs leading-snug text-txt shadow-lg",
            "animate-in fade-in-0 zoom-in-95",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
            className,
          )}
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-surface" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
