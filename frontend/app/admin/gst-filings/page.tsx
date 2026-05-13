"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, FileText, Download } from "lucide-react";

import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  useAdminGSTInvoices,
  useAdminGSTInvoicesSummary,
  downloadGSTInvoicesCSV,
  viewInvoicePDF,
  type GSTInvoiceFilters,
} from "@/lib/queries/admin-gst-invoices";
import { formatINR } from "@/lib/utils";

const SERIES_OPTIONS = ["ALL", "WAL", "QR"] as const;
const FY_OPTIONS = ["ALL", "2026-27", "2025-26"];

function toIsoStart(dateStr: string): string | undefined {
  if (!dateStr) return undefined;
  return `${dateStr}T00:00:00Z`;
}

function toIsoEnd(dateStr: string): string | undefined {
  if (!dateStr) return undefined;
  return `${dateStr}T23:59:59Z`;
}

export default function AdminGSTFilingsPage() {
  const [page, setPage] = useState(1);
  const [financialYear, setFinancialYear] = useState<string>("");
  const [series, setSeries] = useState<"" | "WAL" | "QR">("");
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [interStateMode, setInterStateMode] = useState<string>("");
  const [q, setQ] = useState<string>("");
  const [exporting, setExporting] = useState(false);

  const filters: GSTInvoiceFilters = {
    financial_year: financialYear || undefined,
    series: series || undefined,
    start_date: toIsoStart(startDate),
    end_date: toIsoEnd(endDate),
    is_inter_state:
      interStateMode === "intra" ? false : interStateMode === "inter" ? true : undefined,
    q: q || undefined,
  };

  const listParams: GSTInvoiceFilters = { ...filters, page, limit: 20 };
  const { data, isLoading, error } = useAdminGSTInvoices(listParams);
  const { data: summary } = useAdminGSTInvoicesSummary(filters);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  const resetPage = () => setPage(1);

  const handleExport = async () => {
    setExporting(true);
    try {
      await downloadGSTInvoicesCSV(filters);
    } catch (e) {
      console.error(e);
      alert(`CSV export failed: ${(e as Error).message}`);
    } finally {
      setExporting(false);
    }
  };

  return (
    <AdminOnly>
      <div className="container mx-auto p-6 space-y-6">
        <div>
          <Link
            href="/admin"
            className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1"
          >
            <ChevronLeft className="w-3 h-3" /> Admin dashboard
          </Link>
          <h1 className="text-2xl font-bold mt-2 flex items-center gap-2">
            <FileText className="w-5 h-5 text-emerald-600" />
            GST Filings
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Every issued GST invoice in one place. Filter by financial year,
            series, place of supply, or date range, then export the result as a
            CSV your CA can drop into GSTR-1 reconciliation.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <SummaryCard label="Invoices" value={summary ? String(summary.count) : "—"} />
          <SummaryCard
            label="Taxable value"
            value={summary ? formatINR(summary.total_taxable_value) : "—"}
          />
          <SummaryCard
            label="Total tax (CGST+SGST+IGST)"
            value={summary ? formatINR(summary.total_tax) : "—"}
          />
          <SummaryCard
            label="Invoice value"
            value={summary ? formatINR(summary.total_amount) : "—"}
          />
        </div>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Filters</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exporting}
            >
              <Download className="w-3 h-3 mr-1" />
              {exporting ? "Exporting…" : "Export CSV"}
            </Button>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <div>
                <label className="text-xs text-muted-foreground">Financial year</label>
                <Select
                  value={financialYear || "ALL"}
                  onValueChange={(v) => {
                    setFinancialYear(v === "ALL" ? "" : v);
                    resetPage();
                  }}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FY_OPTIONS.map((fy) => (
                      <SelectItem key={fy} value={fy}>
                        {fy}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Series</label>
                <Select
                  value={series || "ALL"}
                  onValueChange={(v) => {
                    setSeries(v === "ALL" ? "" : (v as "WAL" | "QR"));
                    resetPage();
                  }}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SERIES_OPTIONS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s === "ALL" ? "All" : s === "WAL" ? "Wallet" : "QR (UPI)"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Inter-state</label>
                <Select
                  value={interStateMode || "ALL"}
                  onValueChange={(v) => {
                    setInterStateMode(v === "ALL" ? "" : v);
                    resetPage();
                  }}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All</SelectItem>
                    <SelectItem value="intra">Intra-state (CGST+SGST)</SelectItem>
                    <SelectItem value="inter">Inter-state (IGST)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Search</label>
                <Input
                  className="mt-1"
                  placeholder="Invoice # or customer"
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    resetPage();
                  }}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Issued from</label>
                <Input
                  type="date"
                  className="mt-1"
                  value={startDate}
                  onChange={(e) => {
                    setStartDate(e.target.value);
                    resetPage();
                  }}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Issued to</label>
                <Input
                  type="date"
                  className="mt-1"
                  value={endDate}
                  onChange={(e) => {
                    setEndDate(e.target.value);
                    resetPage();
                  }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {isLoading
                ? "Loading…"
                : `${data?.total ?? 0} ${
                    (data?.total ?? 0) === 1 ? "invoice" : "invoices"
                  }`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {error && (
              <p className="text-sm text-red-600 py-4">
                Failed to load: {error.message}
              </p>
            )}
            {!error && data && data.data.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No invoices match the current filters.
              </p>
            )}
            {!error && data && data.data.length > 0 && (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Invoice #</TableHead>
                      <TableHead>Date</TableHead>
                      <TableHead>Series</TableHead>
                      <TableHead>Customer</TableHead>
                      <TableHead>Operated by</TableHead>
                      <TableHead>PoS</TableHead>
                      <TableHead className="text-right" title="Pre-tax platform/Razorpay commission billed on the invoice as HSN 997158">Gateway</TableHead>
                      <TableHead className="text-right" title="Pre-tax taxable value (energy + gateway combined)">Taxable</TableHead>
                      <TableHead className="text-right">Tax</TableHead>
                      <TableHead className="text-right">Total</TableHead>
                      <TableHead className="text-right">Refund</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.data.map((inv) => (
                      <TableRow key={inv.id}>
                        <TableCell className="text-sm font-mono">
                          {inv.invoice_number}
                        </TableCell>
                        <TableCell className="text-xs">
                          {inv.invoice_date
                            ? new Date(inv.invoice_date).toLocaleDateString("en-IN")
                            : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{inv.series}</Badge>
                        </TableCell>
                        <TableCell className="text-sm">
                          <div className="truncate max-w-[200px]" title={inv.customer_name ?? ""}>
                            {inv.customer_name || "—"}
                          </div>
                          <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                            {inv.customer_identifier || ""}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {inv.franchisee_business_name ? (
                            <div
                              className="truncate max-w-[180px]"
                              title={inv.franchisee_business_name}
                            >
                              {inv.franchisee_business_name}
                              {inv.franchisee_gstin && (
                                <div className="text-xs text-muted-foreground">
                                  {inv.franchisee_gstin}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">VoltLync-owned</span>
                          )}
                        </TableCell>
                        <TableCell className="text-xs">
                          {inv.place_of_supply_state_code || "—"}
                          {inv.is_inter_state && (
                            <span className="ml-1 text-amber-600">(inter)</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right text-sm text-muted-foreground">
                          {inv.gateway_charges && Number(inv.gateway_charges) > 0
                            ? formatINR(inv.gateway_charges)
                            : "—"}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {formatINR(inv.total_taxable_value ?? "0")}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {formatINR(inv.total_tax ?? "0")}
                        </TableCell>
                        <TableCell className="text-right text-sm font-medium">
                          {formatINR(inv.total_amount ?? "0")}
                        </TableCell>
                        <TableCell className="text-right text-sm">
                          {inv.refund_amount && Number(inv.refund_amount) > 0
                            ? formatINR(inv.refund_amount)
                            : "—"}
                        </TableCell>
                        <TableCell>
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await viewInvoicePDF(inv.transaction_id);
                              } catch (e) {
                                alert(`PDF open failed: ${(e as Error).message}`);
                              }
                            }}
                            className="text-xs text-blue-600 hover:underline cursor-pointer"
                          >
                            PDF
                          </button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex justify-between items-center mt-4 text-sm text-muted-foreground">
                <span>
                  Page {page} of {totalPages}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="w-3 h-3 mr-1" />
                    Prev
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                    <ChevronRight className="w-3 h-3 ml-1" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AdminOnly>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-xl font-semibold mt-1">{value}</div>
      </CardContent>
    </Card>
  );
}
