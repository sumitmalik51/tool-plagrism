/**
 * Stable DOM-id helpers shared across passage list / source list components.
 * Used so PassageCard can scroll-and-highlight its source row in Results.tsx
 * (and vice versa) without prop-drilling refs.
 */

function djb2(input: string): string {
  let h = 5381;
  for (let i = 0; i < input.length; i++) {
    h = ((h << 5) + h + input.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

export function sourceAnchorId(url: string | null | undefined): string {
  if (!url) return "source-row-unknown";
  return `source-row-${djb2(url)}`;
}

export function passageAnchorId(passageKey: string): string {
  return `passage-${passageKey}`;
}

/**
 * Cross-component event used to focus a source row from a passage card.
 * Detail = source URL. Listener should call setSelectedSource and scroll to
 * sourceAnchorId(url).
 */
export const SELECT_SOURCE_EVENT = "plg:select-source";

export function dispatchSelectSource(url: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SELECT_SOURCE_EVENT, { detail: url }));
}
