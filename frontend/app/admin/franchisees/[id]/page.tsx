"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Building2,
  MapPin,
  Percent,
  ArrowLeft,
  Unlink,
  Mail,
  CreditCard,
  Pencil,
} from "lucide-react";
import Link from "next/link";

import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
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

import { CommissionUpdate, FranchiseeUpdate } from "@/types/api";
import {
  useFranchisee,
  useFranchiseeStations,
  useCommissionHistory,
  useUpdateFranchisee,
  useUpdateCommission,
  useAssignStations,
  useUnassignStation,
  useResendInvitation,
  useOnboardRazorpay,
} from "@/lib/queries/franchisees";
import { useStations } from "@/lib/queries/stations";

const STATUS_COLORS: Record<string, string> = {
  DRAFT: "bg-gray-100 text-gray-800",
  KYC_SUBMITTED: "bg-blue-100 text-blue-800",
  KYC_UNDER_REVIEW: "bg-yellow-100 text-yellow-800",
  KYC_NEEDS_CLARIFICATION: "bg-orange-100 text-orange-800",
  ACTIVE: "bg-green-100 text-green-800",
  SUSPENDED: "bg-red-100 text-red-800",
  DEACTIVATED: "bg-gray-300 text-gray-700",
};

export default function FranchiseeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id);

  const { data: franchisee, isLoading } = useFranchisee(id);
  const { data: stations } = useFranchiseeStations(id);
  const { data: commissionHistory } = useCommissionHistory(id);

  const [showCommissionDialog, setShowCommissionDialog] = useState(false);
  const [showAssignDialog, setShowAssignDialog] = useState(false);
  const [showBusinessDialog, setShowBusinessDialog] = useState(false);
  const [selectedStationId, setSelectedStationId] = useState<string>("");

  const updateFranchisee = useUpdateFranchisee(id);
  const updateCommission = useUpdateCommission(id);
  const assignStations = useAssignStations(id);
  const unassignStation = useUnassignStation(id);
  const resendInvitation = useResendInvitation();
  const onboardRazorpay = useOnboardRazorpay();

  // Fetch all stations for the assign dialog
  const { data: allStationsData } = useStations({ limit: 100 });
  const unassignedStations = (allStationsData?.data || []).filter(
    (s) => !s.franchisee_id
  );

  if (isLoading) {
    return (
      <AdminOnly>
        <p className="text-center py-8 text-muted-foreground">Loading...</p>
      </AdminOnly>
    );
  }

  if (!franchisee) {
    return (
      <AdminOnly>
        <p className="text-center py-8 text-red-500">Franchisee not found</p>
      </AdminOnly>
    );
  }

  const handleCommissionUpdate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const payload: CommissionUpdate = {
      new_percent: Number(formData.get("new_percent")),
      reason: formData.get("reason") as string,
      effective_from: formData.get("effective_from") as string,
      notes: (formData.get("notes") as string) || undefined,
    };
    updateCommission.mutate(payload, {
      onSuccess: () => setShowCommissionDialog(false),
    });
  };

  const handleBusinessUpdate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    // Only send fields the admin actually filled in. Empty strings map to
    // undefined so the PUT endpoint's exclude_unset=True check leaves
    // existing values alone.
    const raw: Record<string, string> = {};
    formData.forEach((v, k) => {
      const val = String(v).trim();
      if (val) raw[k] = val;
    });
    const payload: FranchiseeUpdate = raw;
    updateFranchisee.mutate(payload, {
      onSuccess: () => setShowBusinessDialog(false),
    });
  };

  const handleAssignStation = () => {
    if (!selectedStationId) return;
    assignStations.mutate([Number(selectedStationId)], {
      onSuccess: () => {
        setShowAssignDialog(false);
        setSelectedStationId("");
      },
    });
  };

  return (
    <AdminOnly>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <div className="flex-1">
            <h1 className="text-2xl font-bold">{franchisee.business_name}</h1>
            <p className="text-muted-foreground">
              {franchisee.contact_name} &middot; {franchisee.contact_email}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => resendInvitation.mutate(id)}
            disabled={resendInvitation.isPending}
            title="Resend Clerk sign-up invitation to the franchisee's contact email"
          >
            <Mail className="w-4 h-4 mr-2" />
            {resendInvitation.isPending ? "Sending…" : "Resend invitation"}
          </Button>
          {!franchisee.razorpay_account_id && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => onboardRazorpay.mutate(id)}
              disabled={onboardRazorpay.isPending}
              title="Create a Razorpay Route linked account — the franchisee completes KYC on Razorpay's hosted page"
            >
              <CreditCard className="w-4 h-4 mr-2" />
              {onboardRazorpay.isPending ? "Starting…" : "Start Razorpay onboarding"}
            </Button>
          )}
          <Badge
            className={STATUS_COLORS[franchisee.status] || ""}
            variant="secondary"
          >
            {franchisee.status.replace(/_/g, " ")}
          </Badge>
        </div>

        {/* Overview Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                Platform Commission
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">
                {Number(franchisee.commission_percent)}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                TDS Rate
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">
                {Number(franchisee.tds_rate_percent)}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                Stations
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{franchisee.station_count}</p>
            </CardContent>
          </Card>
        </div>

        {/* Details */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Business Details</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowBusinessDialog(true)}
            >
              <Pencil className="w-4 h-4 mr-1" /> Edit
            </Button>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Phone:</span>{" "}
              {franchisee.contact_phone}
            </div>
            <div>
              <span className="text-muted-foreground">Business Type:</span>{" "}
              {franchisee.business_type || "Not set"}
            </div>
            <div>
              <span className="text-muted-foreground">PAN:</span>{" "}
              {franchisee.pan_number || "Not set"}
            </div>
            <div>
              <span className="text-muted-foreground">GSTIN:</span>{" "}
              {franchisee.gstin || "Not set"}
            </div>
            <div>
              <span className="text-muted-foreground">State:</span>{" "}
              {franchisee.state || "Not set"}
            </div>
            <div>
              <span className="text-muted-foreground">Razorpay Account:</span>{" "}
              {franchisee.razorpay_account_id || "Not linked"}
            </div>
            {franchisee.notes && (
              <div className="col-span-2">
                <span className="text-muted-foreground">Notes:</span>{" "}
                {franchisee.notes}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Stations */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Assigned Stations</CardTitle>
            <Button size="sm" onClick={() => setShowAssignDialog(true)}>
              <MapPin className="w-4 h-4 mr-1" /> Assign Station
            </Button>
          </CardHeader>
          <CardContent>
            {!stations || stations.length === 0 ? (
              <p className="text-muted-foreground text-center py-4">
                No stations assigned
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Station</TableHead>
                    <TableHead>Address</TableHead>
                    <TableHead>Chargers</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stations.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {s.address || "-"}
                      </TableCell>
                      <TableCell>{s.charger_count}</TableCell>
                      <TableCell>{s.state || "-"}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => unassignStation.mutate(s.id)}
                          disabled={unassignStation.isPending}
                        >
                          <Unlink className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Commission History */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Commission History</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowCommissionDialog(true)}
            >
              <Percent className="w-4 h-4 mr-1" /> Update Commission
            </Button>
          </CardHeader>
          <CardContent>
            {!commissionHistory || commissionHistory.length === 0 ? (
              <p className="text-muted-foreground text-center py-4">
                No commission changes
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Previous</TableHead>
                    <TableHead>New</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Changed By</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {commissionHistory.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="text-sm">
                        {new Date(entry.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        {entry.previous_percent != null
                          ? `${entry.previous_percent}%`
                          : "-"}
                      </TableCell>
                      <TableCell className="font-medium">
                        {entry.new_percent}%
                      </TableCell>
                      <TableCell className="text-sm">
                        {entry.reason.replace(/_/g, " ")}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {entry.changed_by_email || "-"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Commission Update Dialog */}
        <Dialog
          open={showCommissionDialog}
          onOpenChange={setShowCommissionDialog}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Update Commission</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCommissionUpdate} className="space-y-4">
              <div className="space-y-2">
                <Label>Current: {Number(franchisee.commission_percent)}%</Label>
              </div>
              <div className="space-y-2">
                <Label htmlFor="new_percent">New Commission (%)</Label>
                <Input
                  id="new_percent"
                  name="new_percent"
                  type="number"
                  step="0.01"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reason">Reason</Label>
                <Select name="reason" required>
                  <SelectTrigger>
                    <SelectValue placeholder="Select reason" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="CONTRACT_RENEWAL">
                      Contract Renewal
                    </SelectItem>
                    <SelectItem value="PERFORMANCE_ADJUSTMENT">
                      Performance Adjustment
                    </SelectItem>
                    <SelectItem value="PROMOTION">Promotion</SelectItem>
                    <SelectItem value="ADMIN_OVERRIDE">
                      Admin Override
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="effective_from">Effective From</Label>
                <Input
                  id="effective_from"
                  name="effective_from"
                  type="date"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="notes">Notes</Label>
                <Input id="notes" name="notes" />
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowCommissionDialog(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={updateCommission.isPending}>
                  {updateCommission.isPending ? "Updating..." : "Update"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        {/* Business Details Edit Dialog */}
        <Dialog open={showBusinessDialog} onOpenChange={setShowBusinessDialog}>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>Edit Business Details</DialogTitle>
            </DialogHeader>
            <form
              onSubmit={handleBusinessUpdate}
              className="grid grid-cols-2 gap-4"
            >
              <div className="space-y-2 col-span-2">
                <Label htmlFor="business_name">Business Name</Label>
                <Input
                  id="business_name"
                  name="business_name"
                  defaultValue={franchisee.business_name}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="business_type">
                  Business Type
                  <span className="text-xs text-muted-foreground ml-1">
                    (required for Razorpay onboarding)
                  </span>
                </Label>
                <Select
                  name="business_type"
                  defaultValue={franchisee.business_type || undefined}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="INDIVIDUAL">Individual</SelectItem>
                    <SelectItem value="PROPRIETORSHIP">
                      Proprietorship
                    </SelectItem>
                    <SelectItem value="PARTNERSHIP">Partnership</SelectItem>
                    <SelectItem value="PRIVATE_LIMITED">
                      Private Limited
                    </SelectItem>
                    <SelectItem value="LLP">LLP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_name">Contact Name</Label>
                <Input
                  id="contact_name"
                  name="contact_name"
                  defaultValue={franchisee.contact_name}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_phone">Contact Phone</Label>
                <Input
                  id="contact_phone"
                  name="contact_phone"
                  defaultValue={franchisee.contact_phone}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pan_number">PAN</Label>
                <Input
                  id="pan_number"
                  name="pan_number"
                  defaultValue={franchisee.pan_number || ""}
                  placeholder="ABCDE1234F"
                  maxLength={10}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="gstin">GSTIN</Label>
                <Input
                  id="gstin"
                  name="gstin"
                  defaultValue={franchisee.gstin || ""}
                  placeholder="29ABCDE1234F1Z5"
                  maxLength={15}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tan_number">TAN</Label>
                <Input
                  id="tan_number"
                  name="tan_number"
                  defaultValue={franchisee.tan_number || ""}
                  maxLength={10}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="state">State</Label>
                <Input
                  id="state"
                  name="state"
                  defaultValue={franchisee.state || ""}
                  placeholder="Karnataka"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="state_code">State Code</Label>
                <Input
                  id="state_code"
                  name="state_code"
                  defaultValue={franchisee.state_code || ""}
                  placeholder="KA"
                  maxLength={5}
                />
              </div>
              <div className="space-y-2 col-span-2">
                <Label htmlFor="address">Address</Label>
                <Input
                  id="address"
                  name="address"
                  defaultValue={franchisee.address || ""}
                />
              </div>
              <div className="space-y-2 col-span-2">
                <Label htmlFor="notes">Notes</Label>
                <Input
                  id="notes"
                  name="notes"
                  defaultValue={franchisee.notes || ""}
                />
              </div>
              <DialogFooter className="col-span-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowBusinessDialog(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={updateFranchisee.isPending}>
                  {updateFranchisee.isPending ? "Saving..." : "Save"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        {/* Assign Station Dialog */}
        <Dialog open={showAssignDialog} onOpenChange={setShowAssignDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Assign Station</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <Select
                value={selectedStationId}
                onValueChange={setSelectedStationId}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a station" />
                </SelectTrigger>
                <SelectContent>
                  {unassignedStations.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {s.name} - {s.address}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {unassignedStations.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  All stations are already assigned.
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowAssignDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={handleAssignStation}
                disabled={!selectedStationId || assignStations.isPending}
              >
                {assignStations.isPending ? "Assigning..." : "Assign"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </AdminOnly>
  );
}
