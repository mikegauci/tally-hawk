"use client";
import { useEffect, useState } from "react";
import { CloudOff, Loader2 } from "lucide-react";
import { announceWake, unavailable, WAKE_EVENT, type WakeState } from "@/lib/client";
const PING_MS = 3_000;
const GIVE_UP_MS = 90_000;
export function ApiWakeToast() {
  const [state, setState] = useState<WakeState>("awake");
  useEffect(() => {
    const listener = (event: Event) =>
      setState((event as CustomEvent<WakeState>).detail);
    window.addEventListener(WAKE_EVENT, listener);
    return () => window.removeEventListener(WAKE_EVENT, listener);
  }, []);
  // Keep checking while waking, so the toast clears even when the page's own
  // request was a POST that is never retried.
  useEffect(() => {
    if (state !== "waking") return;
    const started = Date.now();
    const timer = setInterval(async () => {
      try {
        const response = await fetch("/api/backend/invoices?limit=1", {
          cache: "no-store",
        });
        if (!unavailable(response)) announceWake("awake");
        else if (Date.now() - started > GIVE_UP_MS) announceWake("unreachable");
      } catch {
        // Network blip; try again on the next tick.
      }
    }, PING_MS);
    return () => clearInterval(timer);
  }, [state]);
  if (state === "awake") return null;
  return (
    <div className="wake-toast" role="status" aria-live="polite">
      {state === "waking" ? (
        <>
          <Loader2 size={16} className="wake-toast-spinner" aria-hidden />
          <div>
            <strong>Waking up the invoice service…</strong>
            <span>
              The demo API runs on free hosting that sleeps when idle. This
              usually takes about 30 seconds; the page will load by itself.
            </span>
          </div>
        </>
      ) : (
        <>
          <CloudOff size={16} aria-hidden />
          <div>
            <strong>The invoice service isn&apos;t responding</strong>
            <span>Refresh the page to try again.</span>
          </div>
        </>
      )}
    </div>
  );
}
