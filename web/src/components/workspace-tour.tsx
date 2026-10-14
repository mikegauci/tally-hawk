"use client";
import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { driver } from "driver.js";
import "driver.js/dist/driver.css";

export const TOUR_STORAGE_KEY = "tallyhawk-tour-v1";

function finishTour() {
  localStorage.setItem(TOUR_STORAGE_KEY, "1");
  const url = new URL(window.location.href);
  if (!url.searchParams.has("tour")) return;
  url.searchParams.delete("tour");
  const query = url.searchParams.toString();
  window.history.replaceState(
    {},
    "",
    query ? `${url.pathname}?${query}` : url.pathname,
  );
}

function buildSteps() {
  return [
    {
      element: '[data-tour="dashboard-kpis"]',
      skipMissingElement: true,
      popover: {
        title: "Overview at a glance",
        description:
          "These cards reflect real uploaded supplier bills — needs review, follow-up, processing, approved, and failed. Nothing here is mock AR data.",
        side: "bottom" as const,
      },
    },
    {
      element: '[data-tour="nav-inbox"]',
      popover: {
        title: "Inbox",
        description:
          "Upload PDF invoices here. Extraction and three-way matching run on the server; you can retry failed items from this queue.",
        side: "right" as const,
      },
    },
    {
      element: '[data-tour="nav-tasks"]',
      popover: {
        title: "My Tasks",
        description:
          "Bills that need a human open here first. Search the review queue and open a document to inspect exceptions.",
        side: "right" as const,
      },
    },
    {
      element: '[data-tour="nav-bills"]',
      popover: {
        title: "Supplier Bills",
        description:
          "Every uploaded bill lives here with workflow status, search, and filters.",
        side: "right" as const,
      },
    },
    {
      element: '[data-tour="sidebar-note"]',
      popover: {
        title: "Review a bill end to end",
        description:
          "From My Tasks, open any flagged bill: PDF beside extracted fields, PO and receipt matching, draft supplier email, and audited approve / reject / query actions. Approval is recorded — it is not payment.",
        side: "right" as const,
        doneBtnText: "Got it",
      },
    },
  ];
}

export function startWorkspaceTour() {
  const instance = driver({
    showProgress: true,
    progressText: "{{current}} of {{total}}",
    nextBtnText: "Next",
    prevBtnText: "Back",
    popoverClass: "tallyhawk-tour-popover",
    steps: buildSteps(),
    onDestroyed: finishTour,
  });
  instance.drive();
  return instance;
}

export function WorkspaceTour() {
  const pathname = usePathname();
  const driverRef = useRef<ReturnType<typeof driver> | null>(null);

  useEffect(() => {
    const forceTour =
      new URLSearchParams(window.location.search).get("tour") === "1";
    const seen = localStorage.getItem(TOUR_STORAGE_KEY);
    if (!forceTour && seen) return;

    if (forceTour && pathname !== "/dashboard") {
      window.location.assign("/dashboard?tour=1");
      return;
    }

    const timer = window.setTimeout(() => {
      if (driverRef.current?.isActive()) return;
      driverRef.current = startWorkspaceTour();
    }, 400);
    return () => {
      window.clearTimeout(timer);
      driverRef.current?.destroy();
      driverRef.current = null;
    };
  }, [pathname]);

  return null;
}

export function replayWorkspaceTour() {
  localStorage.removeItem(TOUR_STORAGE_KEY);
  window.location.assign("/dashboard?tour=1");
}
