import { cookies } from "next/headers";
import {
  configured,
  COOKIE,
  equal,
  sameOrigin,
  sessionToken,
  TTL,
  validDemoToken,
} from "@/lib/auth";

async function rejectSignIn() {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return Response.json(
    { detail: "Incorrect workspace password." },
    { status: 401 },
  );
}

async function establishSession() {
  (await cookies()).set(COOKIE, sessionToken(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    maxAge: TTL,
    path: "/",
  });
  return Response.json({ ok: true });
}

export async function POST(request: Request) {
  if (!sameOrigin(request))
    return Response.json(
      { detail: "Invalid request origin." },
      { status: 403 },
    );
  if (!configured())
    return Response.json(
      {
        detail: "Workspace connection is not configured. Follow web/README.md.",
      },
      { status: 503 },
    );
  const form = await request.formData();
  const demoToken = String(form.get("demo_token") || "");
  if (demoToken) {
    if (!validDemoToken(demoToken)) return rejectSignIn();
    return establishSession();
  }
  if (!equal(String(form.get("password") || ""), process.env.WEB_PASSWORD!)) {
    return rejectSignIn();
  }
  return establishSession();
}
export async function DELETE(request: Request) {
  if (!sameOrigin(request))
    return Response.json(
      { detail: "Invalid request origin." },
      { status: 403 },
    );
  (await cookies()).delete(COOKIE);
  return Response.json({ ok: true });
}
