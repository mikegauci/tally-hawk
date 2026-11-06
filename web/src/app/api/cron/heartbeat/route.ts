export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const cronSecret = process.env.CRON_SECRET;
  if (!cronSecret || request.headers.get("authorization") !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const supabaseUrl = process.env.SUPABASE_URL;
    const publishableKey = process.env.SUPABASE_PUBLISHABLE_KEY;
    if (!supabaseUrl || !publishableKey) {
      throw new Error("Supabase heartbeat is not configured");
    }

    const response = await fetch(`${supabaseUrl.replace(/\/$/, "")}/rest/v1/invoices?select=id&limit=1`, {
      headers: { apikey: publishableKey },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(30_000),
    });

    if (!response.ok) {
      throw new Error(`Supabase returned HTTP ${response.status}`);
    }
    if (!Array.isArray(await response.json())) {
      throw new Error("Unexpected Supabase response");
    }

    return Response.json({ ok: true, timestamp: new Date().toISOString() });
  } catch (error) {
    console.error("Supabase heartbeat failed:", error);
    return Response.json({ ok: false, error: "Heartbeat failed" }, { status: 500 });
  }
}
