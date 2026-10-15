import { test, expect } from "@playwright/test";
const id = "11111111-1111-4111-8111-111111111111";
test.beforeEach(async ({ request }) => {
  await request.get("http://127.0.0.1:8109/reset");
});
async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.evaluate(() => localStorage.setItem("tallyhawk-tour-v2", "1"));
  await page.getByLabel("Workspace password").fill("test-password");
  await page.getByRole("button", { name: "Sign in to workspace" }).click();
  // The first test of a run waits for the dev server to compile the dashboard.
  await expect(page).toHaveURL("/dashboard", { timeout: 30_000 });
}
test("overview dashboard shows KPIs from the API", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Needs review")).toBeVisible();
  await expect(page.getByText("Recent supplier bills")).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "supplier-invoice.pdf" }),
  ).toBeVisible({ timeout: 30_000 });
});
test("demo magic link signs in without password and opens product tour", async ({
  page,
}) => {
  await page.goto("/login");
  await page.evaluate(() => {
    localStorage.removeItem("tallyhawk-tour-v2");
    sessionStorage.clear();
  });
  await page.goto("/login?token=test-demo-token");
  await expect(page).toHaveURL(/\/dashboard\?tour=1$/);
  await expect(page.getByText("Overview at a glance")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByText("My Tasks is where humans step in"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/\/tasks\?tour=1$/);
  await expect(
    page.getByRole("heading", { name: "Review queue" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  await page.reload();
  await expect(page.getByText("Overview at a glance")).not.toBeVisible();
});

test("rejects invalid demo magic link", async ({ page }) => {
  await page.goto("/login?token=not-a-valid-demo-token");
  await expect(page).toHaveURL("/login");
  await expect(page.locator(".error-message")).toContainText(
    "Incorrect workspace password",
  );
});

test("protects workspace pages and API, rejects cross-origin sign-in", async ({
  page,
  request,
}) => {
  await page.goto("/tasks");
  await expect(page).toHaveURL("/login");
  expect((await request.get("/api/backend/invoices")).status()).toBe(401);
  expect(
    (
      await request.post("/api/session", {
        headers: { origin: "https://attacker.example" },
        form: { password: "test-password" },
      })
    ).status(),
  ).toBe(403);
});
test("sign-in, queue search and live counts", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "My Tasks" }).click();
  await expect(
    page.getByRole("link", {
      name: "Kestrel Building Materials Ltd INV-2026-104",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Review queue" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Search documents" })
    .fill("no-such-invoice");
  await expect(page.getByText("No matching documents")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByText("EUR 118.00")).toBeVisible();
});
test("validates upload and sends a valid document", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Inbox" }).click();
  await page.getByLabel("Choose supplier invoices").setInputFiles({
    name: "bad.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("invalid"),
  });
  await expect(page.getByText("Unsupported file type.")).toBeVisible();
  await page.getByLabel("Choose supplier invoices").setInputFiles({
    name: "invoice.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 test"),
  });
  await page.getByRole("button", { name: "Upload & process" }).click();
  await expect(
    page.getByText("Uploaded · Extraction and matching queued"),
  ).toBeVisible();
});
test("requires an exception note, records approval and preserves reviewer identity", async ({
  page,
}) => {
  await login(page);
  await page.goto(`/payables/bills/${id}`);
  await page.getByRole("button", { name: "Approve bill", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Confirm", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Review note")
    .fill("Verified with the purchase order owner.");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByText("Your review decision has been recorded."),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByText("Test reviewer", { exact: false })).toBeVisible();
});
test("saves corrections and retains original extracted evidence", async ({
  page,
}) => {
  await login(page);
  await page.goto(`/payables/bills/${id}`);
  await page
    .getByLabel("Supplier name", { exact: true })
    .fill("Corrected supplier");
  await expect(
    page.getByRole("button", { name: "Approve bill", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save & recheck" }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(
    page.getByText("Corrections saved and matching completed."),
  ).toBeVisible();
  await expect(
    page.getByText("Originally extracted: Kestrel Building Materials Ltd"),
  ).toBeVisible();
});
test("shows errors without claiming an empty queue", async ({ page }) => {
  await login(page);
  await page.route("**/api/backend/review-queue?*", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Service temporarily unavailable." }),
    }),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.locator(".error-banner")).toContainText(
    "Service temporarily unavailable.",
  );
});
test("responsive review separates document and data", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  await page.goto(`/payables/bills/${id}`);
  await expect(page.getByLabel("Supplier name", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Document", exact: true }).click();
  await expect(
    page.getByLabel("Supplier name", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Original document" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
test("desktop visual capture and no overflow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await page.getByRole("link", { name: "My Tasks" }).click();
  await expect(
    page.getByRole("link", {
      name: "Kestrel Building Materials Ltd INV-2026-104",
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/inbox-desktop.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("shows a wake-up notice while the API cold-starts, then loads", async ({
  page,
  request,
}) => {
  // Put the API to sleep before sign-in, so the dashboard's first load hits it.
  await request.get("http://127.0.0.1:8109/sleep?requests=4");
  await login(page);
  const toast = page.getByRole("status").filter({
    hasText: "Waking up the invoice service",
  });
  await expect(toast).toBeVisible();
  await expect(toast).not.toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByRole("cell", { name: "supplier-invoice.pdf" }),
  ).toBeVisible();
});

test("stops uploading at the demo cap and explains why", async ({
  page,
  request,
}) => {
  await request.get("http://127.0.0.1:8109/cap?uploads=1");
  await login(page);
  await page.getByRole("link", { name: "Inbox" }).click();
  const pdf = (name: string) => ({
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 test"),
  });
  await page
    .getByLabel("Choose supplier invoices")
    .setInputFiles([pdf("first.pdf"), pdf("second.pdf"), pdf("third.pdf")]);
  await page.getByRole("button", { name: "Upload & process" }).click();
  const banner = page
    .getByRole("alert")
    .filter({ hasText: "Demo limit reached." });
  await expect(banner).toContainText("1 invoices per visit");
  await expect(
    page.getByText("Uploaded · Extraction and matching queued"),
  ).toHaveCount(1);
  // The rest are left ready rather than marked as failed.
  await expect(page.getByText("2 ready to upload")).toBeVisible();
});

test("uploads a sample invoice through the normal pipeline", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("link", { name: "Inbox" }).click();
  const card = page
    .getByRole("listitem")
    .filter({ hasText: "Supplier's own sums are wrong" });
  await expect(card).toContainText("Expected: Supplier query drafted");
  await card.getByRole("button", { name: /Try sample/ }).click();
  await expect(page.getByText("inv_008.pdf")).toBeVisible();
  await expect(
    page.getByText("Uploaded · Extraction and matching queued"),
  ).toBeVisible();
});

test("pipeline tab shows each step with time, tokens and cost", async ({
  page,
}) => {
  await login(page);
  await page.goto(`/payables/bills/${id}`);
  await page.getByRole("tab", { name: "Pipeline" }).click();
  await expect(page.getByLabel("Pipeline totals")).toContainText(
    "13.3 s in total · 2 model calls · 3,950 tokens · $0.0410",
  );
  const steps = page.locator(".pipeline-steps > li");
  await expect(steps).toHaveCount(7);
  await expect(steps.first()).toContainText("Read the invoice");
  await expect(steps.first()).toContainText("$0.0300");
  await expect(steps.filter({ hasText: "Three-way match" })).toContainText(
    "Rules",
  );
  await expect(
    steps.filter({ hasText: "Draft the supplier email" }),
  ).toContainText("950 tokens (700 in, 250 out)");
});
