export const dynamic = "force-dynamic";
// Allow the Render API time to wake up before querying Supabase.
export const maxDuration = 300;

export async function GET(request: Request) {
  const cronSecret = process.env.CRON_SECRET;
  if (!cronSecret || request.headers.get("authorization") !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const apiUrl = process.env.TALLYHAWK_API_URL;
    const apiKey = process.env.TALLYHAWK_API_KEY;
    if (!apiUrl || !apiKey) {
      throw new Error("TallyHawk API is not configured");
    }

    const response = await fetch(`${apiUrl.replace(/\/$/, "")}/invoices?limit=1`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(240_000),
    });

    if (!response.ok) {
      throw new Error(`TallyHawk API returned HTTP ${response.status}`);
    }
    if (!Array.isArray(await response.json())) {
      throw new Error("Unexpected TallyHawk API response");
    }

    return Response.json({ ok: true, timestamp: new Date().toISOString() });
  } catch (error) {
    console.error("Supabase heartbeat failed:", error);
    return Response.json({ ok: false, error: "Heartbeat failed" }, { status: 500 });
  }
}
