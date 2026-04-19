"use client";

import { useEffect, useRef } from "react";
import { useScanJobsStore } from "@/lib/stores/scan-jobs-store";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Mounts an EventSource for the active job's progress stream and pushes
 *  updates into the global store. When the stream emits "done", we pull the
 *  final job record (which carries the result) so the dashboard can render it.
 */
export default function useScanJobStream() {
  const active = useScanJobsStore((s) => s.active);
  const updateActive = useScanJobsStore((s) => s.updateActive);
  const refreshActive = useScanJobsStore((s) => s.refreshActive);
  const reconnectRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) return;
    if (active.status === "completed" || active.status === "failed") return;

    const docId = active.document_id;
    const url = `${API_URL}/api/v1/scan-progress/${encodeURIComponent(docId)}`;
    let closed = false;
    let es: EventSource | null = null;

    const connect = () => {
      if (closed) return;
      // eslint-disable-next-line no-console
      console.log("[scan-jobs] SSE connect", url);
      es = new EventSource(url);

      es.onopen = () => {
        // eslint-disable-next-line no-console
        console.log("[scan-jobs] SSE open");
      };

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as {
            stage: string;
            message: string;
            percent: number;
          };
          // eslint-disable-next-line no-console
          console.log("[scan-jobs] event", data);
          if (data.stage === "done") {
            void refreshActive();
            closed = true;
            es?.close();
            return;
          }
          if (data.stage === "error") {
            updateActive({
              status: "failed",
              error: data.message,
              progress: { stage: data.stage, message: data.message, percent: 0 },
            });
            closed = true;
            es?.close();
            return;
          }
          updateActive({
            status: "running",
            progress: {
              stage: data.stage,
              message: data.message,
              percent: Math.max(0, Math.min(100, data.percent || 0)),
            },
          });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("[scan-jobs] bad SSE payload", err);
        }
      };

      es.onerror = () => {
        // eslint-disable-next-line no-console
        console.warn("[scan-jobs] SSE error — will retry in 2s");
        es?.close();
        if (closed) return;
        void refreshActive();
        reconnectRef.current = window.setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      closed = true;
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      es?.close();
    };
  }, [active?.document_id, active?.status, updateActive, refreshActive, active]);
}
