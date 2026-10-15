"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import {
  Inbox,
  LayoutDashboard,
  ListTodo,
  ReceiptText,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  ShieldCheck,
  Menu,
  X,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { HawkMark } from "@/components/hawk-mark";
import { ThemeToggle } from "@/components/theme-toggle";
import { replayWorkspaceTour, WorkspaceTour } from "@/components/workspace-tour";
import { ApiWakeToast } from "@/components/api-wake-toast";
const subscribe = (callback: () => void) => {
  window.addEventListener("sidebar-change", callback);
  return () => window.removeEventListener("sidebar-change", callback);
};
const tourId: Record<string, string> = {
  "/dashboard": "nav-dashboard",
  "/inbox": "nav-inbox",
  "/tasks": "nav-tasks",
  "/payables/bills": "nav-bills",
};
const groups = [
  {
    label: "Workspace",
    items: [
      { label: "Overview", href: "/dashboard", icon: LayoutDashboard },
      { label: "Inbox", href: "/inbox", icon: Inbox },
      { label: "My Tasks", href: "/tasks", icon: ListTodo },
    ],
  },
  {
    label: "Accounts payable",
    items: [
      { label: "Supplier Bills", href: "/payables/bills", icon: ReceiptText },
    ],
  },
];
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const collapsed = useSyncExternalStore(
    subscribe,
    () => localStorage.getItem("sidebar-collapsed") === "true",
    () => false,
  );
  const [mobile, setMobile] = useState(false);
  return (
    <div className={`app-shell ${collapsed ? "is-collapsed" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {mobile && (
        <button
          className="mobile-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={`sidebar ${mobile ? "mobile-open" : ""}`}>
        <Link href="/dashboard" className="brand">
          <span className="brand-mark">
            <HawkMark size={26} />
          </span>
          <span className="sidebar-label">
            TallyHawk<span className="brand-caption">Finance workspace</span>
          </span>
        </Link>
        <div className="workspace-label sidebar-label">
          <span className="workspace-avatar">AP</span>
          <div>
            Accounts payable<small>Supplier invoice workspace</small>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {groups.map((group) => (
            <div className="nav-group" key={group.label}>
              <p className="sidebar-label">{group.label}</p>
              {group.items.map((item) => (
                <Link
                  title={item.label}
                  onClick={() => setMobile(false)}
                  key={item.href}
                  href={item.href}
                  data-tour={tourId[item.href]}
                  aria-current={path.startsWith(item.href) ? "page" : undefined}
                  className={
                    path.startsWith(item.href) ? "nav-item active" : "nav-item"
                  }
                >
                  <item.icon size={18} />
                  <span className="sidebar-label">{item.label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note sidebar-label" data-tour="sidebar-note">
            <ShieldCheck size={18} />
            <p>
              A clear trail for every bill.
              <small>
                Review source documents and keep decisions on record.
              </small>
            </p>
          </div>
          <Button
            variant="ghost"
            className="collapse-button"
            onClick={() => {
              localStorage.setItem("sidebar-collapsed", String(!collapsed));
              window.dispatchEvent(new Event("sidebar-change"));
            }}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
            <span className="sidebar-label">Collapse navigation</span>
          </Button>
          <ThemeToggle />
          <Button variant="ghost" onClick={() => replayWorkspaceTour()}>
            <Sparkles />
            <span className="sidebar-label">Product tour</span>
          </Button>
          <Button
            variant="ghost"
            onClick={async () => {
              await fetch("/api/session", { method: "DELETE" });
              window.location.assign("/login");
            }}
          >
            <LogOut />
            <span className="sidebar-label">Sign out</span>
          </Button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Button
            variant="ghost"
            size="icon"
            className="mobile-menu"
            aria-label={mobile ? "Close navigation" : "Open navigation"}
            onClick={() => setMobile(!mobile)}
          >
            {mobile ? <X /> : <Menu />}
          </Button>
          <span>
            Workspace <span className="breadcrumb-divider">/</span>{" "}
            <strong>
              {path.startsWith("/dashboard")
                ? "Overview"
                : path.startsWith("/inbox")
                  ? "Inbox"
                  : path.startsWith("/tasks")
                    ? "My Tasks"
                    : "Supplier Bills"}
            </strong>
          </span>
          <span className="topbar-label">
            <span className="workspace-avatar small">AP</span>Finance team
          </span>
        </header>
        <main id="main">{children}</main>
        <footer className="app-footer">
          TallyHawk{" "}
          <span>
            Accounts payable · Amounts include tax unless stated otherwise
          </span>
        </footer>
      </div>
      <WorkspaceTour />
      <ApiWakeToast />
    </div>
  );
}
