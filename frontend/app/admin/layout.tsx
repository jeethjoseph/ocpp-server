"use client";

import React from "react";
import {
  LayoutDashboard,
  MapPin,
  Zap,
  Receipt,
  QrCode,
  Store,
  FileText,
  Cpu,
  ScrollText,
  UserCog,
} from "lucide-react";
import SidebarShell, { type NavItem } from "@/components/SidebarShell";
import RouteErrorBoundary from "@/components/RouteErrorBoundary";

const adminItems: NavItem[] = [
  { name: "Dashboard", href: "/admin", icon: LayoutDashboard },
  { name: "Stations", href: "/admin/stations", icon: MapPin },
  { name: "Chargers", href: "/admin/chargers", icon: Zap },
  { name: "Transactions", href: "/admin/transactions", icon: Receipt },
  { name: "QR Codes", href: "/admin/qr-codes", icon: QrCode },
  { name: "Franchisees", href: "/admin/franchisees", icon: Store },
  { name: "GST Filings", href: "/admin/gst-filings", icon: FileText },
  { name: "Firmware", href: "/admin/firmware", icon: Cpu },
  { name: "Logs", href: "/admin/logs", icon: ScrollText },
  { name: "Users", href: "/admin/users", icon: UserCog },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <SidebarShell items={adminItems}>
      <RouteErrorBoundary>{children}</RouteErrorBoundary>
    </SidebarShell>
  );
}
