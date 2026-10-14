export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    cache: "no-store",
  });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Your session expired. Please sign in.");
  }
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The request could not be completed. Check your fields and try again.",
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
