"use client";

import React from "react";
import { usePathname } from "next/navigation";
import ErrorBoundary from "@/components/ErrorBoundary";

// Thin client wrapper that feeds the current pathname to ErrorBoundary as its
// reset key, so a tripped boundary auto-clears when the admin/franchisee user
// navigates to another route (class components can't use the usePathname hook
// directly). Use this at section layout boundaries instead of ErrorBoundary.
export default function RouteErrorBoundary({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  return <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>;
}
