"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Sparkles,
  LayoutDashboard,
  ListTodo,
  CalendarDays,
  Bell,
  Settings,
  LogOut,
  ArrowUpRight,
  PanelLeftClose,
  Menu,
} from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "./provider";
import { NotificationBell } from "./notification-bell";
import { unsubscribeBrowser } from "@/lib/notifications";
const links = [
  ["/assistant", "Assistant", Sparkles],
  ["/dashboard", "Overview", LayoutDashboard],
  ["/tasks", "Tasks", ListTodo],
  ["/calendar", "Calendar", CalendarDays],
  ["/reminders", "Reminders", Bell],
  ["/settings", "Settings", Settings],
] as const;
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, preferences, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  if (["/login", "/register"].includes(path)) return children;
  return (
    <div className="workspace">
      <a href="#content" className="skip-link">
        Skip to content
      </a>
      <button
        className="mobile-menu icon-button"
        aria-label="Open navigation"
        onClick={() => setOpen(!open)}
      >
        <Menu />
      </button>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <Link href="/assistant" className="brand">
          <span className="brand-icon">t</span>tempo<span className="brand-dot">.</span>
        </Link>
        <button
          className="mobile-close icon-button"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        >
          <PanelLeftClose />
        </button>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav>
          {links.map(([href, label, Icon]) => (
            <Link
              onClick={() => setOpen(false)}
              className={path === href ? "nav-link active" : "nav-link"}
              href={href}
              key={href}
            >
              <Icon size={19} />
              {label}
              {href === "/assistant" && <span className="nav-badge">AI</span>}
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="tiny-spark">
            <Sparkles size={17} />
          </span>
          <strong>A little more breathing room.</strong>
          <p>Make a plan that works with your day.</p>
          <Link href="/tasks">
            Plan your next task <ArrowUpRight size={15} />
          </Link>
        </div>
        <div className="profile">
          <span className="avatar">{user?.name.slice(0, 1).toUpperCase()}</span>
          <div>
            <strong>{user?.name}</strong>
            <small>{preferences?.timezone}</small>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={async () => {
              try {
                await unsubscribeBrowser();
                await api.logout();
                await refresh();
                router.push("/login");
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
        {error && <p role="alert">{error}</p>}
      </aside>
      <div className="main-wrap">
        <header className="topbar">
          <span>
            Personal workspace <span className="slash">/</span>{" "}
            <b>{links.find((l) => l[0] === path)?.[1] || "Overview"}</b>
          </span>
          <div className="topbar-right">
            <span className="timezone-dot" />
            {preferences?.timezone}
            {user && (
              <NotificationBell key={user.id} zone={preferences?.timezone || "Africa/Accra"} />
            )}
          </div>
        </header>
        <main id="content">{children}</main>
      </div>
    </div>
  );
}
