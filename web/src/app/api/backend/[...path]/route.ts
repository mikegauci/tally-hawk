import { authenticated, sameOrigin } from "@/lib/auth";
export const maxDuration = 300;
const uuid = "[0-9a-fA-F-]{36}";
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!(await authenticated()))
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
    if (path.endsWith("/file"))
      resultHeaders.set("Content-Disposition", "inline");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: resultHeaders,
    });
  } catch {
    return Response.json(
      {
        detail:
          "The invoice service could not respond. Refresh to check whether your request completed before trying again.",
      },
      { status: 502 },
    );
  }
}
export { proxy as GET, proxy as POST };
