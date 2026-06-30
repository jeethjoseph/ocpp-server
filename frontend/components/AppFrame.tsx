"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Navbar from "@/components/Navbar";

// Chooses the app shell by route. Operator sections (/admin, /franchisee) own
// their own chrome via per-section layouts (the sidebar shell), so here we
// render bare children. Everything else (customer/public) keeps the top
// navbar + centered content column.
export default function AppFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isOperator =
    pathname?.startsWith("/admin") || pathname?.startsWith("/franchisee");

  if (isOperator) {
    return <>{children}</>;
  }

  return (
    <>
      <Navbar />
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">{children}</main>
    </>
  );
}
