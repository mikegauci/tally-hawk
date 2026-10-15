"use client";
import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { api } from "@/lib/client";
import type { QueueItem } from "@/lib/types";

export const TOUR_STORAGE_KEY = "tallyhawk-tour-v2";

const ACTIVE_KEY = "tallyhawk-tour-active";
const STEP_KEY = "tallyhawk-tour-step";
const BILL_ID_KEY = "tallyhawk-tour-bill-id";
const PAUSING_KEY = "tallyhawk-tour-pausing";

function tourQuery(extra?: Record<string, string>) {
  const params = new URLSearchParams({ tour: "1", ...extra });
  return `?${params.toString()}`;
}

function stripTourParams() {
  const url = new URL(window.location.href);
  url.searchParams.delete("tour");
  url.searchParams.delete("tourTab");
  const query = url.searchParams.toString();
  window.history.replaceState(
    {},
    "",
    query ? `${url.pathname}?${query}` : url.pathname,
  );
}

function completeTour() {
  localStorage.setItem(TOUR_STORAGE_KEY, "1");
  sessionStorage.removeItem(ACTIVE_KEY);
  sessionStorage.removeItem(STEP_KEY);
  sessionStorage.removeItem(BILL_ID_KEY);
  stripTourParams();
}

function abandonTour() {
  sessionStorage.removeItem(ACTIVE_KEY);
  sessionStorage.removeItem(STEP_KEY);
  sessionStorage.removeItem(BILL_ID_KEY);
  stripTourParams();
}

function pathForStep(step: number, billId: string | null) {
  if (step <= 1) return "/dashboard";
  if (step <= 5) return "/tasks";
  if (step >= 6 && billId) return `/payables/bills/${billId}`;
  return null;
}

function pathnameMatches(expected: string, pathname: string) {
  if (expected.startsWith("/payables/bills/")) {
    return pathname.startsWith("/payables/bills/");
  }
  return pathname === expected;
}

function buildSteps(
  pause: (nextStep: number, path: string, extra?: Record<string, string>) => void,
  finish: () => void,
  driverInstance: () => ReturnType<typeof driver> | null,
): DriveStep[] {
  return [
    {
      element: '[data-tour="dashboard-kpis"]',
      skipMissingElement: true,
      popover: {
        title: "Overview at a glance",
        description:
          "These cards reflect real uploaded supplier bills — needs review, follow-up, processing, approved, and failed. Nothing here is mock AR data.",
        side: "bottom",
      },
    },
    {
      element: '[data-tour="nav-tasks"]',
      popover: {
        title: "My Tasks is where humans step in",
        description:
          "After the server reads the PDF and runs matching, bills with exceptions land in My Tasks — not the ones that auto-approve cleanly.",
        side: "right",
        onNextClick: () => {
          driverInstance()?.destroy();
          pause(2, "/tasks");
        },
      },
    },
    {
      element: '[data-tour="tasks-intro"]',
      skipMissingElement: true,
      popover: {
        title: "Review queue",
        description:
          "This is your exception inbox. Each row is a supplier bill the matcher flagged for a person — quantity or price mismatches, missing PO references, or other review routes.",
        side: "bottom",
      },
    },
    {
      element: '[data-tour="tasks-metrics"]',
      skipMissingElement: true,
      popover: {
        title: "Queue size vs processing",
        description:
          "Needs review counts bills waiting here. Processing counts uploads still being extracted and matched against purchase orders and goods receipts.",
        side: "bottom",
      },
    },
    {
      element: '[data-tour="tasks-queue"]',
      skipMissingElement: true,
      popover: {
        title: "Open a bill to investigate",
        description:
          "Search by supplier or invoice number, then open a row. You will compare the original PDF with extracted fields and PO/receipt checks.",
        side: "top",
        onNextClick: () => {
          void (async () => {
            driverInstance()?.destroy();
            try {
              const queue = await api<QueueItem[]>("review-queue");
              if (queue.length === 0) {
                sessionStorage.setItem(ACTIVE_KEY, "1");
                sessionStorage.setItem(STEP_KEY, "5");
                sessionStorage.setItem(PAUSING_KEY, "1");
                window.location.assign(`/tasks${tourQuery()}`);
                return;
              }
              const billId = queue[0].invoice_id;
              sessionStorage.setItem(BILL_ID_KEY, billId);
              sessionStorage.setItem(ACTIVE_KEY, "1");
              sessionStorage.setItem(STEP_KEY, "6");
              sessionStorage.setItem(PAUSING_KEY, "1");
              window.location.assign(
                `/payables/bills/${billId}${tourQuery({ tourTab: "matching" })}`,
              );
            } catch {
              finish();
            }
          })();
        },
      },
    },
    {
      popover: {
        title: "No bills in the queue yet",
        description:
          "Load the curated demo set from the repo root: uv run tallyhawk demo load (needs DATABASE_URL and OPENAI_API_KEY). Then refresh My Tasks to walk through a real matching example.",
        doneBtnText: "Got it",
        onNextClick: () => finish(),
        onCloseClick: () => finish(),
      },
    },
    {
      element: '[data-tour="bill-source"]',
      skipMissingElement: true,
      popover: {
        title: "Side-by-side review",
        description:
          "The supplier’s PDF stays on the left. Extracted header and line values on the right should match what is printed — corrections are re-checked on the server.",
        side: "right",
      },
    },
    {
      element: '[data-tour="bill-matching-tab"]',
      skipMissingElement: true,
      popover: {
        title: "Matching tab",
        description:
          "This is the three-way match view: invoice amounts vs what the purchase order allowed vs what goods receipt recorded as received.",
        side: "bottom",
      },
    },
    {
      element: '[data-tour="bill-matching-panel"]',
      skipMissingElement: true,
      popover: {
        title: "Exceptions explained",
        description:
          "Each card is a deterministic rule outcome — for example billing more units than were received. Supplier-facing issues may include a draft email; nothing is sent automatically.",
        side: "left",
      },
    },
    {
      element: '[data-tour="bill-match-lines"]',
      skipMissingElement: true,
      popover: {
        title: "Line-level three-way match",
        description:
          "Quantity billed is on the invoice. Quantity ordered comes from the PO. Quantity received comes from the goods receipt. PO unit price is compared to the invoice unit price.",
        side: "top",
      },
    },
    {
      element: '[data-tour="bill-decisions"]',
      skipMissingElement: true,
      popover: {
        title: "Human decision",
        description:
          "Approve, reject, or record supplier follow-up with a note. Every action is audited. Approval is recorded in the workspace — it is not payment.",
        side: "top",
        doneBtnText: "Got it",
        onNextClick: () => finish(),
        onCloseClick: () => finish(),
      },
    },
  ];
}

export function startWorkspaceTour(startStep = 0) {
  const driverRef: { current: ReturnType<typeof driver> | null } = {
    current: null,
  };
  const finish = () => {
    completeTour();
    driverRef.current?.destroy();
  };
  const pause = (
    nextStep: number,
    path: string,
    extra?: Record<string, string>,
  ) => {
    sessionStorage.setItem(ACTIVE_KEY, "1");
    sessionStorage.setItem(STEP_KEY, String(nextStep));
    sessionStorage.setItem(PAUSING_KEY, "1");
    driverRef.current?.destroy();
    window.location.assign(`${path}${tourQuery(extra)}`);
  };

  const instance = driver({
    showProgress: true,
    progressText: "{{current}} of {{total}}",
    nextBtnText: "Next",
    prevBtnText: "Back",
    popoverClass: "tallyhawk-tour-popover",
    steps: buildSteps(pause, finish, () => driverRef.current),
    onDestroyed: () => {
      if (sessionStorage.getItem(PAUSING_KEY)) {
        sessionStorage.removeItem(PAUSING_KEY);
        return;
      }
      if (localStorage.getItem(TOUR_STORAGE_KEY)) return;
      abandonTour();
    },
  });
  driverRef.current = instance;
  instance.drive(startStep);
  return instance;
}

export function WorkspaceTour() {
  const pathname = usePathname();
  const driverRef = useRef<ReturnType<typeof driver> | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const forceTour = params.get("tour") === "1";
    const completed = localStorage.getItem(TOUR_STORAGE_KEY);
    let active = sessionStorage.getItem(ACTIVE_KEY) === "1";
    let step = Number(sessionStorage.getItem(STEP_KEY) || "0");

    if (forceTour) {
      if (!active) {
        active = true;
        if (!sessionStorage.getItem(STEP_KEY)) {
          step = 0;
          sessionStorage.setItem(STEP_KEY, "0");
        }
        sessionStorage.setItem(ACTIVE_KEY, "1");
      }
    } else if (!active) {
      if (completed) return;
      if (pathname !== "/dashboard") return;
      active = true;
      step = 0;
      sessionStorage.setItem(ACTIVE_KEY, "1");
      sessionStorage.setItem(STEP_KEY, "0");
    }

    if (!active) return;

    const billId = sessionStorage.getItem(BILL_ID_KEY);
    const expected = pathForStep(step, billId);
    if (expected && !pathnameMatches(expected, pathname)) {
      const extra =
        step >= 6 ? { tourTab: "matching" } : undefined;
      window.location.assign(`${expected}${tourQuery(extra)}`);
      return;
    }

    const timer = window.setTimeout(() => {
      if (driverRef.current?.isActive()) return;
      driverRef.current = startWorkspaceTour(step);
    }, 450);
    return () => {
      window.clearTimeout(timer);
      if (sessionStorage.getItem(PAUSING_KEY)) return;
      driverRef.current?.destroy();
      driverRef.current = null;
    };
  }, [pathname]);

  return null;
}

export function replayWorkspaceTour() {
  localStorage.removeItem(TOUR_STORAGE_KEY);
  sessionStorage.removeItem(ACTIVE_KEY);
  sessionStorage.removeItem(STEP_KEY);
  sessionStorage.removeItem(BILL_ID_KEY);
  window.location.assign(`/dashboard${tourQuery()}`);
}
