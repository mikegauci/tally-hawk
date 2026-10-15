import { sameOrigin, sessionId } from "@/lib/auth";
export const maxDuration = 300;
const uuid = "[0-9a-fA-F-]{36}";
// Tells the browser the API itself is unreachable or still starting (Render's
// free tier sleeps when idle), as opposed to an error the API returned.
const UNAVAILABLE = "X-TallyHawk-Unavailable";
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const session = await sessionId();
  if (!session)
    return Response.json({ detail: "Please sign in again." }, { status: 401 });
  if (request.method !== "GET" && !sameOrigin(request))
    return Response.json(
      { detail: "Invalid request origin." },
      { status: 403 },
    );
  const path = (await context.params).path.join("/");
  const allowed =
    request.method === "GET"
      ? new RegExp(`^(invoices|review-queue|invoices/${uuid}(/file)?)$`)
      : new RegExp(`^(invoices|invoices/${uuid}/(review|process))$`);
  if (!allowed.test(path))
    return Response.json({ detail: "Not found." }, { status: 404 });
  const headers = new Headers({
    Authorization: `Bearer ${process.env.TALLYHAWK_API_KEY}`,
    // Counts uploads per visit for the demo caps (src/tallyhawk/limits.py).
    "X-TallyHawk-Session": session,
  });
  let body: BodyInit | undefined;
  try {
    if (request.method === "POST" && path === "invoices") {
      if (Number(request.headers.get("content-length")) > 4_200_000)
        return Response.json(
          { detail: "Files must be 4 MB or smaller." },
          { status: 413 },
        );
      const form = await request.formData();
      const file = form.get("file");
      if (!(file instanceof File) || file.size === 0 || file.size > 4_000_000)
        return Response.json(
          { detail: "Choose a non-empty file up to 4 MB." },
          { status: 400 },
        );
      if (
        !["application/pdf", "image/png", "image/jpeg", "image/webp"].includes(
          file.type,
        )
      )
        return Response.json(
          { detail: "Choose a PDF, PNG, JPEG, or WebP file." },
          { status: 415 },
        );
      body = new FormData();
      body.append("file", file);
    } else if (request.method === "POST") {
      headers.set("Content-Type", "application/json");
      if (path.endsWith("/review")) {
        const data = await request.json();
        if (
          !["approve", "reject", "send_query", "correct"].includes(data.action)
        )
          return Response.json(
            { detail: "Invalid review action." },
            { status: 400 },
          );
        body = JSON.stringify({
          ...data,
          reviewer: process.env.WEB_REVIEWER_NAME || "Workspace reviewer",
        });
      }
    }
    const input = new URL(request.url);
    const query = new URLSearchParams();
    for (const key of ["status", "limit", "offset"])
      if (input.searchParams.has(key))
        query.set(key, input.searchParams.get(key)!);
    const url = `${process.env.TALLYHAWK_API_URL!.replace(/\/$/, "")}/${path}?${query}`;
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(240_000),
    });
    const resultHeaders = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    resultHeaders.set(
      "Content-Type",
      upstream.headers.get("Content-Type") || "application/json",
    );
    if (
      [502, 503, 504].includes(upstream.status) &&
      !resultHeaders.get("Content-Type")!.includes("application/json")
    )
      return Response.json(
        { detail: "The invoice service is starting up. Try again shortly." },
        { status: 503, headers: { [UNAVAILABLE]: "1" } },
      );
    if (path.endsWith("/file"))
      resultHeaders.set("Content-Disposition", "inline");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: resultHeaders,
    });
  } catch {
    const base = process.env.TALLYHAWK_API_URL?.replace(/\/$/, "") ?? "";
    const local = /localhost|127\.0\.0\.1/.test(base);
    const hint = local
      ? "Start the API from the repo root: uv run uvicorn tallyhawk.api:app --env-file .env --reload"
      : base
        ? `Check that the API at ${base} is deployed and reachable (see docs/DEPLOY.md).`
        : "Set TALLYHAWK_API_URL in the web environment.";
    return Response.json(
      {
        detail: `The invoice service could not respond. ${hint}`,
      },
      { status: 502, headers: { [UNAVAILABLE]: "1" } },
    );
  }
}
export { proxy as GET, proxy as POST };
