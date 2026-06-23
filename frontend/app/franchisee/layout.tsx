"use client";

import React from "react";
import {
  LayoutDashboard,
  MapPin,
  Receipt,
  Wallet,
  QrCode,
  User,
} from "lucide-react";
import SidebarShell, { type NavItem } from "@/components/SidebarShell";

const franchiseeItems: NavItem[] = [
  { name: "Dashboard", href: "/franchisee", icon: LayoutDashboard },
  { name: "Stations", href: "/franchisee/stations", icon: MapPin },
  { name: "Transactions", href: "/franchisee/transactions", icon: Receipt },
  { name: "Settlements", href: "/franchisee/settlements", icon: Wallet },
  { name: "QR Codes", href: "/franchisee/qr-codes", icon: QrCode },
  { name: "Profile", href: "/franchisee/profile", icon: User },
];

export default function FranchiseeLayout({ children }: { children: React.ReactNode }) {
  return <SidebarShell items={franchiseeItems}>{children}</SidebarShell>;
}
