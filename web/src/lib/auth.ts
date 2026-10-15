import "server-only";
import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
export const COOKIE = "tallyhawk-session";
export const TTL = 60 * 60 * 8;
export function configured() {
  return Boolean(
    process.env.WEB_PASSWORD &&
    process.env.SESSION_SECRET &&
    process.env.TALLYHAWK_API_URL &&
    process.env.TALLYHAWK_API_KEY,
  );
}
export function demoTokenConfigured() {
  return Boolean(process.env.WEB_DEMO_TOKEN);
}
export function validDemoToken(token: string) {
  const expected = process.env.WEB_DEMO_TOKEN;
  return Boolean(expected && token && equal(token, expected));
}
function sign(value: string) {
  return createHmac("sha256", process.env.SESSION_SECRET!)
    .update(value)
    .digest("hex");
}
export function equal(a: string, b: string) {
  const x = Buffer.from(a),
    y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}
// Cookie value: `<expiry>.<session id>.<signature>`. The random session id lets the API
// count uploads per visit for the demo caps (src/tallyhawk/limits.py).
export function sessionToken() {
  const value = `${Math.floor(Date.now() / 1000) + TTL}.${randomUUID()}`;
  return `${value}.${sign(value)}`;
}
async function session() {
  if (!configured()) return null;
  const value = (await cookies()).get(COOKIE)?.value;
  if (!value) return null;
  const [expiry, id, signature] = value.split(".");
  const valid =
    /^\d+$/.test(expiry) &&
    /^[0-9a-f-]{36}$/.test(id || "") &&
    Number(expiry) > Date.now() / 1000 &&
    equal(signature || "", sign(`${expiry}.${id}`));
  return valid ? { id } : null;
}
export async function authenticated() {
  return (await session()) !== null;
}
export async function sessionId() {
  return (await session())?.id ?? null;
}
export function sameOrigin(request: Request) {
  return request.headers.get("origin") === new URL(request.url).origin;
}
