// The API on Render's free tier sleeps when idle and takes ~30s to wake. The proxy
// marks those responses; GETs retry until the API answers, and the wake toast
// (components/api-wake-toast.tsx) tells the user what is happening.
export const WAKE_EVENT = "tallyhawk-api-wake";
export type WakeState = "waking" | "awake" | "unreachable";
const RETRY_MS = 3_000;
const GIVE_UP_MS = 90_000;
const SLOW_GET_MS = 5_000;
let waking = false;
export function announceWake(state: WakeState) {
  waking = state === "waking";
  window.dispatchEvent(new CustomEvent(WAKE_EVENT, { detail: state }));
}
export function unavailable(response: Response) {
  return response.headers.get("X-TallyHawk-Unavailable") === "1";
}
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
// 429: a demo cap or the demo's OpenAI budget was reached (src/tallyhawk/limits.py).
export const demoLimitReached = (error: unknown) =>
  error instanceof ApiError && error.status === 429;
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const get = (init?.method ?? "GET").toUpperCase() === "GET";
  const started = Date.now();
  // A sleeping Render service often holds the request open instead of failing.
  const slow = get
    ? setTimeout(() => announceWake("waking"), SLOW_GET_MS)
    : undefined;
  let response!: Response;
  try {
    for (;;) {
      response = await fetch(`/api/backend/${path}`, {
        ...init,
        cache: "no-store",
      });
      if (!unavailable(response)) break;
      announceWake("waking");
      // Never retry a POST: an upload or review could be applied twice.
      if (!get || Date.now() - started > GIVE_UP_MS) {
        if (get) announceWake("unreachable");
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
    }
  } finally {
    clearTimeout(slow);
  }
  if (waking && !unavailable(response)) announceWake("awake");
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Your session expired. Please sign in.");
  }
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : "The request could not be completed. Check your fields and try again.",
      response.status,
    );
  return data;
}
export function money(amount: number, currency: string) {
  try {
    return new Intl.NumberFormat("en-MT", {
      style: "currency",
      currency,
      currencyDisplay: "code",
    }).format(amount);
  } catch {
    return `${currency} ${amount}`;
  }
}
export function date(value: string) {
  return new Intl.DateTimeFormat("en-MT", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Europe/Malta",
  }).format(new Date(value));
}
export const statusLabels: Record<string, string> = {
  uploaded: "Received",
  processing: "Processing",
  approved: "Approved",
  awaiting_review: "Needs review",
  vendor_queried: "Supplier follow-up",
  rejected: "Rejected",
  failed: "Processing failed",
};
