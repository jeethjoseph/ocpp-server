"use client";

import Link from "next/link";
import { BarChart3, ArrowRight } from "lucide-react";
import { AdminOnly } from "@/components/RoleWrapper";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";

const reports = [
  {
    href: "/admin/reports/churn",
    title: "Customer churn & retention",
    description:
      "Weekly or monthly QR customer cohorts — how many first-time customers come back and keep charging. Live from Postgres; refresh on demand.",
    icon: BarChart3,
  },
];

export default function ReportsPage() {
  return (
    <AdminOnly fallback={<p className="p-6 text-muted-foreground">Admins only.</p>}>
      <div className="mx-auto max-w-5xl px-4 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Product & business analytics, computed live and refreshed only when
            you ask.
          </p>
        </header>

        <div className="grid gap-4 sm:grid-cols-2">
          {reports.map((r) => (
            <Link key={r.href} href={r.href} className="group block">
              <Card className="h-full transition-colors group-hover:border-primary/50">
                <CardHeader>
                  <div className="mb-2 flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <r.icon className="size-5" />
                  </div>
                  <CardTitle className="flex items-center justify-between">
                    {r.title}
                    <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </CardTitle>
                  <CardDescription>{r.description}</CardDescription>
                </CardHeader>
                <CardContent />
              </Card>
            </Link>
          ))}
        </div>
      </div>
    </AdminOnly>
  );
}
