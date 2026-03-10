"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AdminOnly } from "@/components/RoleWrapper";
import { QrCode, Plus, Eye, X, Search } from "lucide-react";
import Link from "next/link";
import { useQRCodes, useCreateQRCode, useCloseQRCode } from "@/lib/queries/qr-codes";
import { useChargers } from "@/lib/queries/chargers";

export default function QRCodesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [selectedChargerId, setSelectedChargerId] = useState<string>("");

  const { data, isLoading } = useQRCodes({
    page,
    limit: 20,
    status: statusFilter === "all" ? undefined : statusFilter,
    search: search || undefined,
  });

  const { data: chargersData } = useChargers({ limit: 100 });
  const createMutation = useCreateQRCode();
  const closeMutation = useCloseQRCode();

  const handleCreate = async () => {
    if (!selectedChargerId) return;
    await createMutation.mutateAsync(parseInt(selectedChargerId));
    setShowCreateDialog(false);
    setSelectedChargerId("");
  };

  const totalPages = data ? Math.ceil(data.total / 20) : 0;

  return (
    <AdminOnly>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-card-foreground">
              Payment QR Codes
            </h1>
            <p className="text-muted-foreground mt-1">
              Manage Razorpay UPI QR codes for appless charging
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Create QR Code
          </Button>
        </div>

        {/* Filters */}
        <Card className="mb-6">
          <CardContent className="pt-6">
            <div className="flex gap-4 items-center">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search by charger name..."
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPage(1);
                  }}
                  className="pl-10"
                />
              </div>
              <Select
                value={statusFilter}
                onValueChange={(v) => {
                  setStatusFilter(v);
                  setPage(1);
                }}
              >
                <SelectTrigger className="w-[150px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="inactive">Inactive</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* QR Codes Table */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <QrCode className="h-5 w-5" />
              QR Codes {data && `(${data.total})`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="text-center py-8 text-muted-foreground">
                Loading...
              </div>
            ) : !data?.data.length ? (
              <div className="text-center py-8 text-muted-foreground">
                No QR codes found. Create one to get started.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-3 px-2 font-medium">Charger</th>
                      <th className="text-left py-3 px-2 font-medium">
                        Charge Point ID
                      </th>
                      <th className="text-left py-3 px-2 font-medium">QR Code ID</th>
                      <th className="text-left py-3 px-2 font-medium">Status</th>
                      <th className="text-right py-3 px-2 font-medium">Payments</th>
                      <th className="text-right py-3 px-2 font-medium">Revenue</th>
                      <th className="text-left py-3 px-2 font-medium">Created</th>
                      <th className="text-right py-3 px-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.data.map((qr) => (
                      <tr key={qr.id} className="border-b hover:bg-accent/50">
                        <td className="py-3 px-2 font-medium">
                          {qr.charger_name}
                        </td>
                        <td className="py-3 px-2 text-muted-foreground font-mono text-xs">
                          {qr.charge_point_string_id}
                        </td>
                        <td className="py-3 px-2 text-muted-foreground font-mono text-xs">
                          {qr.razorpay_qr_code_id}
                        </td>
                        <td className="py-3 px-2">
                          <Badge
                            variant={qr.is_active ? "default" : "destructive"}
                          >
                            {qr.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>
                        <td className="py-3 px-2 text-right">
                          {qr.payment_count ?? 0}
                        </td>
                        <td className="py-3 px-2 text-right font-medium">
                          {qr.total_revenue
                            ? `₹${Number(qr.total_revenue).toFixed(2)}`
                            : "₹0.00"}
                        </td>
                        <td className="py-3 px-2 text-muted-foreground">
                          {new Date(qr.created_at).toLocaleDateString()}
                        </td>
                        <td className="py-3 px-2 text-right">
                          <div className="flex gap-1 justify-end">
                            <Link href={`/admin/qr-codes/${qr.id}`}>
                              <Button variant="outline" size="sm">
                                <Eye className="h-3 w-3 mr-1" />
                                View
                              </Button>
                            </Link>
                            {qr.is_active && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => closeMutation.mutate(qr.id)}
                                disabled={closeMutation.isPending}
                              >
                                <X className="h-3 w-3 mr-1" />
                                Close
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex justify-between items-center mt-4">
                <p className="text-sm text-muted-foreground">
                  Page {page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Create QR Dialog */}
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Payment QR Code</DialogTitle>
            </DialogHeader>
            <div className="py-4">
              <label className="text-sm font-medium mb-2 block">
                Select Charger
              </label>
              <Select
                value={selectedChargerId}
                onValueChange={setSelectedChargerId}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Choose a charger..." />
                </SelectTrigger>
                <SelectContent>
                  {chargersData?.data.map((charger) => (
                    <SelectItem
                      key={charger.id}
                      value={charger.id.toString()}
                    >
                      {charger.name} ({charger.charge_point_string_id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowCreateDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!selectedChargerId || createMutation.isPending}
              >
                {createMutation.isPending ? "Creating..." : "Create QR Code"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </AdminOnly>
  );
}
