"use client";
import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Loader2,
  LockKeyhole,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";

async function signIn(body: FormData) {
  const response = await fetch("/api/session", {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail);
}

export default function Login() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) return;
    window.history.replaceState({}, "", "/login");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot magic-link sign-in
    setBusy(true);
    setError("");
    const form = new FormData();
    form.set("demo_token", token);
    signIn(form)
      .then(() => window.location.assign("/dashboard?tour=1"))
      .catch((err) => {
        setError((err as Error).message);
        setBusy(false);
      });
  }, []);

  return (
    <main className="login-page">
      <div className="login-theme">
        <ThemeToggle showLabel={false} />
      </div>
      <div className="login-card">
        <span className="brand-mark">
          <ArrowDownToLine />
        </span>
        <p className="eyebrow">TALLYHAWK WORKSPACE</p>
        <h1>
          A little less paperwork.
          <br />A lot more clarity.
        </h1>
        <p>
          Upload supplier invoices, inspect the details, and give every
          exception a clear next step.
        </p>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await signIn(new FormData(event.currentTarget));
              window.location.assign("/dashboard");
            } catch (err) {
              setError((err as Error).message);
              setBusy(false);
            }
          }}
        >
          <label htmlFor="password">Workspace password</label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            disabled={busy}
          />
          {error && (
            <p role="alert" className="error-message">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}Sign
            in to workspace
          </Button>
        </form>
        <small>
          <LockKeyhole size={14} /> Private access for your finance team
        </small>
      </div>
    </main>
  );
}
