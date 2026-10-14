"use client";
import { useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Loader2,
  LockKeyhole,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
export default function Login() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
              const response = await fetch("/api/session", {
                method: "POST",
                body: new FormData(event.currentTarget),
              });
              const data = await response.json();
              if (!response.ok) throw new Error(data.detail);
              window.location.assign("/dashboard");
            } catch (error) {
              setError((error as Error).message);
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
