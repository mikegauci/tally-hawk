"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const cycle = ["system", "light", "dark"] as const;

function labelFor(theme: (typeof cycle)[number] | undefined) {
  if (theme === "light") return "Light mode";
  if (theme === "dark") return "Dark mode";
  return "System theme";
}

function hintFor(theme: (typeof cycle)[number] | undefined) {
  if (theme === "light") return "Switch to dark mode";
  if (theme === "dark") return "Use system setting";
  return "Switch to light mode";
}

export function ThemeToggle({ showLabel = true }: { showLabel?: boolean }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const current =
    theme === "light" || theme === "dark" || theme === "system"
      ? theme
      : "system";

  if (!mounted) {
    return (
      <Button variant="ghost" className="theme-toggle" disabled aria-hidden>
        <Monitor size={18} />
        {showLabel ? <span className="sidebar-label">Theme</span> : null}
      </Button>
    );
  }

  const Icon =
    current === "light" ? Sun : current === "dark" ? Moon : Monitor;

  return (
    <Button
      variant="ghost"
      className="theme-toggle"
      aria-label={hintFor(current)}
      title={labelFor(current)}
      onClick={() => {
        const index = cycle.indexOf(current);
        setTheme(cycle[(index + 1) % cycle.length]);
      }}
    >
      <Icon size={18} />
      {showLabel ? (
        <span className="sidebar-label">{labelFor(current)}</span>
      ) : null}
    </Button>
  );
}
