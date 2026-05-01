"use client";

import { useEffect } from "react";
import { useScanJobsStore } from "@/lib/stores/scan-jobs-store";
import useScanJobStream from "@/lib/hooks/use-scan-job-stream";

/** Invisible mount point that keeps the SSE subscription + localStorage
 *  rehydration alive on every dashboard page, regardless of which page the
 *  user is on. Renders nothing.
 */
export default function ScanJobMount() {
  const loadFromStorage = useScanJobsStore((s) => s.loadFromStorage);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  useScanJobStream();
  return null;
}
