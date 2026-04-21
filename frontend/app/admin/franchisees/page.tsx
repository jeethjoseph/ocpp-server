"use client";

import { useState } from "react";
import { Plus, Search } from "lucide-react";
import Link from "next/link";

import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { FranchiseeCreate } from "@/types/api";
import { useFranchisees, useCreateFranchisee } from "@/lib/queries/franchisees";

const STATUS_COLORS: Record<string, string> = {
  DRAFT: "bg-gray-100 text-gray-800",
  KYC_SUBMITTED: "bg-blue-100 text-blue-800",
  KYC_UNDER_REVIEW: "bg-yellow-100 text-yellow-800",
  KYC_NEEDS_CLARIFICATION: "bg-orange-100 text-orange-800",
  ACTIVE: "bg-green-100 text-green-800",
  SUSPENDED: "bg-red-100 text-red-800",
  DEACTIVATED: "bg-gray-300 text-gray-700",
};

export default function AdminFranchiseesPage() {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [currentPage, setCurrentPage] = useState(1);

  const { data, isLoading, error } = useFranchisees({
    page: currentPage,
    limit: 10,
    search: searchTerm || undefined,
    status: statusFilter || undefined,
  });

  const createMutation = useCreateFranchisee();

  const franchisees = data?.data || [];
  const totalPages = data ? Math.ceil(data.total / 10) : 1;

  const handleCreate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const payload: FranchiseeCreate = {
      business_name: formData.get("business_name") as string,
      contact_name: formData.get("contact_name") as string,
      contact_email: formData.get("contact_email") as string,
      contact_phone: formData.get("contact_phone") as string,
      commission_percent: Number(formData.get("commission_percent")) || 20,
    };
    createMutation.mutate(payload, {
      onSuccess: () => setShowCreateDialog(false),
    });
  };

  return (
    <AdminOnly>
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold">Franchisees</h1>
            <p className="text-muted-foreground">
              Manage franchise partners and station assignments
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            <Plus className="w-4 h-4 mr-2" />
            Add Franchisee
          </Button>
        </div>

        <Card>
          <CardHeader>
            <div className="flex gap-4 items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search by name or email..."
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="pl-10"
                />
              </div>
              <Select
                value={statusFilter}
                onValueChange={(val) => {
                  setStatusFilter(val === "ALL" ? "" : val);
                  setCurrentPage(1);
                }}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder="All Statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Statuses</SelectItem>
                  <SelectItem value="DRAFT">Draft</SelectItem>
                  <SelectItem value="ACTIVE">Active</SelectItem>
                  <SelectItem value="SUSPENDED">Suspended</SelectItem>
                  <SelectItem value="DEACTIVATED">Deactivated</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <p className="text-center py-8 text-muted-foreground">
                Loading...
              </p>
            ) : error ? (
              <p className="text-center py-8 text-red-500">
                Error loading franchisees
              </p>
            ) : franchisees.length === 0 ? (
              <p className="text-center py-8 text-muted-foreground">
                No franchisees found
              </p>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Business</TableHead>
                      <TableHead>Contact</TableHead>
                      <TableHead>Commission</TableHead>
                      <TableHead>Stations</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Created</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {franchisees.map((f) => (
                      <TableRow key={f.id}>
                        <TableCell>
                          <Link
                            href={`/admin/franchisees/${f.id}`}
                            className="font-medium text-primary hover:underline"
                          >
                            {f.business_name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm">{f.contact_name}</div>
                          <div className="text-xs text-muted-foreground">
                            {f.contact_email}
                          </div>
                        </TableCell>
                        <TableCell>{Number(f.commission_percent)}%</TableCell>
                        <TableCell>{f.station_count}</TableCell>
                        <TableCell>
                          <Badge
                            className={STATUS_COLORS[f.status] || ""}
                            variant="secondary"
                          >
                            {f.status.replace(/_/g, " ")}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {new Date(f.created_at).toLocaleDateString()}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {totalPages > 1 && (
                  <div className="flex justify-center gap-2 mt-4">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage <= 1}
                      onClick={() => setCurrentPage((p) => p - 1)}
                    >
                      Previous
                    </Button>
                    <span className="flex items-center text-sm text-muted-foreground">
                      Page {currentPage} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage >= totalPages}
                      onClick={() => setCurrentPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Create Dialog */}
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Franchisee</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="business_name">Business Name</Label>
                <Input id="business_name" name="business_name" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_name">Contact Name</Label>
                <Input id="contact_name" name="contact_name" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_email">Contact Email</Label>
                <Input
                  id="contact_email"
                  name="contact_email"
                  type="email"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_phone">Contact Phone</Label>
                <Input id="contact_phone" name="contact_phone" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="commission_percent">
                  Platform Commission (%)
                </Label>
                <Input
                  id="commission_percent"
                  name="commission_percent"
                  type="number"
                  step="0.01"
                  defaultValue="20"
                />
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowCreateDialog(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "Creating..." : "Create"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>
    </AdminOnly>
  );
}
