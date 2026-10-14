import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
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
export function sessionToken() {
  const expiry = String(Math.floor(Date.now() / 1000) + TTL);
  return `${expiry}.${sign(expiry)}`;
}
export async function authenticated() {
  if (!configured()) return false;
  const value = (await cookies()).get(COOKIE)?.value;
  if (!value) return false;
  const [expiry, signature] = value.split(".");
  return (
    /^\d+$/.test(expiry) &&
    Number(expiry) > Date.now() / 1000 &&
    equal(signature || "", sign(expiry))
  );
}
export function sameOrigin(request: Request) {
  return request.headers.get("origin") === new URL(request.url).origin;
}
