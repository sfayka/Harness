"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Settings, Bell } from "lucide-react";

export function DashboardHeader() {
  const pathname = usePathname();
  const navItems = [
    { href: "/tasks", label: "Tasks" },
    { href: "/verification", label: "Verification" },
    { href: "/reconciliation", label: "Reconciliation" },
    { href: "/reviews", label: "Reviews" },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center justify-between px-6">
        <div className="flex items-center gap-6">
          <Link href="/tasks" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-foreground">
              <Activity className="h-4 w-4 text-background" />
            </div>
            <span className="text-lg font-semibold tracking-tight">
              Harness
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.href}
                href={item.href}
                active={pathname === item.href}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
            <Bell className="h-4 w-4" />
            <span className="sr-only">Notifications</span>
          </button>
          <button className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
            <Settings className="h-4 w-4" />
            <span className="sr-only">Settings</span>
          </button>
          <div className="ml-2 h-8 w-8 rounded-full bg-muted flex items-center justify-center text-xs font-medium">
            AO
          </div>
        </div>
      </div>
    </header>
  );
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
        active
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
      }`}
    >
      {children}
    </Link>
  );
}
