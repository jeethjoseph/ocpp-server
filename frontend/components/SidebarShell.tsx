"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "@/contexts/ThemeContext";
import { useUserRole } from "@/components/RoleWrapper";
import { SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { Menu, X, type LucideIcon } from "lucide-react";

export interface NavItem {
  name: string;
  href: string;
  icon: LucideIcon;
}

// Section roots ("/admin", "/franchisee") match exactly so they don't light up
// for every child route; deeper links match themselves and their descendants.
function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  const isRoot = href === "/admin" || href === "/franchisee";
  return isRoot ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
}

const themeIcons: Record<string, string> = { light: "☀️", dark: "🌙", system: "💻" };

function SidebarContent({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { role, isAdmin, isFranchisee, isLoaded } = useUserRole();

  const cycleTheme = () => {
    const themes: ("light" | "dark" | "system")[] = ["light", "dark", "system"];
    setTheme(themes[(themes.indexOf(theme) + 1) % themes.length]);
  };

  const homeHref = isAdmin ? "/admin" : isFranchisee ? "/franchisee" : "/";

  return (
    <div className="flex h-full flex-col bg-card border-r border-border">
      {/* Logo */}
      <div className="flex items-center h-16 px-4 border-b border-border">
        <Link href={homeHref} className="flex items-center" aria-label="voltNOW home" onClick={onNavigate}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/voltnow-logo.png" alt="voltNOW" className="block dark:hidden h-7 w-auto" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/voltnow-logo-light.png" alt="voltNOW" className="hidden dark:block h-7 w-auto" />
        </Link>
      </div>

      {/* Nav links */}
      <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-200 ${
                active
                  ? "bg-accent text-card-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-card-foreground"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Account block */}
      <div className="border-t border-border p-3 space-y-3">
        <div className="flex items-center justify-between">
          <button
            onClick={cycleTheme}
            className="p-2 rounded-md text-muted-foreground hover:text-card-foreground hover:bg-accent transition-colors duration-200 text-lg"
            title={`Current theme: ${theme}. Click to cycle themes.`}
          >
            {themeIcons[theme]}
          </button>
          {isLoaded && role && (
            <span
              className={`px-2 py-1 rounded-full text-xs font-medium ${
                isAdmin
                  ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                  : "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
              }`}
            >
              {role}
            </span>
          )}
        </div>
        <SignedIn>
          <div className="flex items-center">
            <UserButton />
          </div>
        </SignedIn>
        <SignedOut>
          <SignInButton>
            <Button variant="default" size="sm" className="w-full">
              Sign In
            </Button>
          </SignInButton>
        </SignedOut>
      </div>
    </div>
  );
}

export default function SidebarShell({
  items,
  children,
}: {
  items: NavItem[];
  children: React.ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  // Drawer a11y: close on Escape and move focus into the drawer when it opens.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    drawerRef.current?.focus();
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="min-h-screen">
      {/* Desktop: fixed sidebar */}
      <aside className="hidden md:block md:fixed md:inset-y-0 md:left-0 md:w-64 md:z-30">
        <SidebarContent items={items} />
      </aside>

      {/* Mobile: top strip with hamburger */}
      <div className="md:hidden sticky top-0 z-30 flex items-center justify-between h-14 px-4 border-b border-border bg-card">
        <Link href="/" className="flex items-center" aria-label="voltNOW home">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/voltnow-logo.png" alt="voltNOW" className="block dark:hidden h-6 w-auto" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/voltnow-logo-light.png" alt="voltNOW" className="hidden dark:block h-6 w-auto" />
        </Link>
        <button
          onClick={() => setDrawerOpen(true)}
          aria-label="Open menu"
          className="p-2 rounded-md text-muted-foreground hover:text-card-foreground hover:bg-accent transition-colors duration-200"
        >
          <Menu className="h-6 w-6" />
        </button>
      </div>

      {/* Mobile: off-canvas drawer */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawerOpen(false)} />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            tabIndex={-1}
            className="absolute inset-y-0 left-0 w-64 shadow-xl outline-none"
          >
            <button
              onClick={() => setDrawerOpen(false)}
              aria-label="Close menu"
              className="absolute top-4 right-3 z-50 p-1 text-muted-foreground hover:text-card-foreground"
            >
              <X className="h-5 w-5" />
            </button>
            <SidebarContent items={items} onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      {/* Content */}
      <div className="md:pl-64">
        <main className="p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
