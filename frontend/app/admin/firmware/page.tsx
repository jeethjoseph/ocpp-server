"use client";

import React, { useState } from "react";
import { AdminOnly } from "@/components/RoleWrapper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import {
  useFirmwareFiles,
  useUploadFirmware,
  useDeleteFirmware,
  useUpdateStatus,
  useCancelUpdate,
  useMarkInstalled,
  useMarkFailed,
} from "@/lib/queries/firmware";
import { Upload, Trash2, RefreshCw, AlertCircle, CheckCircle2, Clock, XCircle, X } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export default function AdminFirmwarePage() {
  const { getToken } = useAuth();
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadVersion, setUploadVersion] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");

  // Queries - they will automatically wait for auth using isAuthReady from context
  const { data: firmwareData, isLoading: isLoadingFirmware } = useFirmwareFiles({ is_active: true });
  const { data: statusData } = useUpdateStatus();

  // Mutations
  const uploadMutation = useUploadFirmware();
  const deleteMutation = useDeleteFirmware();
  const cancelMutation = useCancelUpdate();
  const markInstalledMutation = useMarkInstalled();
  const markFailedMutation = useMarkFailed();

  const firmwareFiles = firmwareData?.data || [];
  const inProgressUpdates = statusData?.in_progress || [];
  const summary = statusData?.summary;

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || !uploadVersion) {
      return;
    }

    await uploadMutation.mutateAsync({
      file: uploadFile,
      version: uploadVersion,
      getToken,
      description: uploadDescription,
    });

    // Reset form and close dialog
    setUploadFile(null);
    setUploadVersion("");
    setUploadDescription("");
    setShowUploadDialog(false);
  };

  const handleCancelUpdate = async (updateId: number) => {
    if (confirm("Cancel this pending update? Only allowed before any attempt has been made.")) {
      await cancelMutation.mutateAsync(updateId);
    }
  };

  const handleMarkInstalled = async (updateId: number) => {
    if (confirm("Mark this update as INSTALLED? This will also update the charger's firmware version.")) {
      await markInstalledMutation.mutateAsync(updateId);
    }
  };

  const handleMarkFailed = async (updateId: number) => {
    if (confirm("Mark this update as FAILED? The admin must re-trigger if the charger needs another attempt.")) {
      await markFailedMutation.mutateAsync(updateId);
    }
  };

  const handleDelete = async (firmwareId: number, version: string) => {
    if (confirm(`Are you sure you want to delete firmware version ${version}?`)) {
      await deleteMutation.mutateAsync(firmwareId);
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ReactElement }> = {
      PENDING: { variant: "secondary", icon: <Clock className="h-3 w-3" /> },
      INSTALLED: { variant: "outline", icon: <CheckCircle2 className="h-3 w-3" /> },
      FAILED: { variant: "destructive", icon: <XCircle className="h-3 w-3" /> },
      CANCELLED: { variant: "secondary", icon: <X className="h-3 w-3" /> },
    };

    const { variant, icon } = variants[status] || { variant: "secondary" as const, icon: <Clock className="h-3 w-3" /> };

    return (
      <Badge variant={variant} className="flex items-center gap-1">
        {icon}
        {status}
      </Badge>
    );
  };

  const formatRelative = (iso?: string): string => {
    if (!iso) return "—";
    const target = new Date(iso).getTime();
    const diff = target - Date.now();
    const absMin = Math.abs(diff) / 60000;
    if (absMin < 1) return diff > 0 ? "in <1m" : "<1m ago";
    if (absMin < 60) return `${diff > 0 ? "in " : ""}${Math.round(absMin)}m${diff > 0 ? "" : " ago"}`;
    const absHr = absMin / 60;
    if (absHr < 24) return `${diff > 0 ? "in " : ""}${absHr.toFixed(1)}h${diff > 0 ? "" : " ago"}`;
    return new Date(iso).toLocaleString();
  };

  return (
    <AdminOnly fallback={<div className="flex items-center justify-center min-h-screen">Access Denied</div>}>
      <div className="container mx-auto py-8 space-y-6">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold">Firmware Management</h1>
            <p className="text-muted-foreground">Manage OTA firmware updates for your chargers</p>
          </div>
          <Button onClick={() => setShowUploadDialog(true)}>
            <Upload className="h-4 w-4 mr-2" />
            Upload Firmware
          </Button>
        </div>

        {/* Status Summary */}
        {summary && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Pending</CardDescription>
                <CardTitle className="text-2xl">{summary.pending}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Installed Today</CardDescription>
                <CardTitle className="text-2xl">{summary.completed_today}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Failed Today</CardDescription>
                <CardTitle className="text-2xl text-destructive">{summary.failed_today}</CardTitle>
              </CardHeader>
            </Card>
          </div>
        )}

        {/* In-Progress Updates */}
        {inProgressUpdates.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Active Updates</CardTitle>
              <CardDescription>
                Completion is confirmed by BootNotification (or admin manual close). Retries: up to 5 attempts over ~6h with exponential backoff.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Charger</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Attempts</TableHead>
                    <TableHead>Last Attempt</TableHead>
                    <TableHead>Next Retry</TableHead>
                    <TableHead>Initiated</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inProgressUpdates.map((update) => (
                    <TableRow key={update.update_id}>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        #{update.update_id}
                      </TableCell>
                      <TableCell>
                        <div>
                          <div className="font-medium">{update.charger_name}</div>
                          <div className="text-sm text-muted-foreground">{update.charge_point_id}</div>
                        </div>
                      </TableCell>
                      <TableCell>{update.firmware_version}</TableCell>
                      <TableCell>{getStatusBadge(update.status)}</TableCell>
                      <TableCell>{update.attempt_count}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelative(update.last_attempt_at)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelative(update.next_retry_at)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelative(update.initiated_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {update.status === "PENDING" && update.attempt_count === 0 && (
                            <Button
                              variant="ghost"
                              size="sm"
                              title="Cancel (only before any attempt)"
                              onClick={() => handleCancelUpdate(update.update_id)}
                              disabled={cancelMutation.isPending}
                            >
                              <X className="h-4 w-4 text-destructive" />
                            </Button>
                          )}
                          {update.status === "PENDING" && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                title="Mark installed"
                                onClick={() => handleMarkInstalled(update.update_id)}
                                disabled={markInstalledMutation.isPending}
                              >
                                <CheckCircle2 className="h-4 w-4 text-green-600" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                title="Mark failed"
                                onClick={() => handleMarkFailed(update.update_id)}
                                disabled={markFailedMutation.isPending}
                              >
                                <XCircle className="h-4 w-4 text-destructive" />
                              </Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {/* Firmware Files Library */}
        <Card>
          <CardHeader>
            <CardTitle>Firmware Library</CardTitle>
            <CardDescription>Available firmware versions for deployment</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoadingFirmware ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
              </div>
            ) : firmwareFiles.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>No firmware files uploaded yet</p>
                <p className="text-sm">Upload your first firmware to get started</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Filename</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Checksum (MD5)</TableHead>
                    <TableHead>Uploaded</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {firmwareFiles.map((firmware) => (
                    <TableRow key={firmware.id}>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        #{firmware.id}
                      </TableCell>
                      <TableCell className="font-medium">{firmware.version}</TableCell>
                      <TableCell>{firmware.filename}</TableCell>
                      <TableCell>{(firmware.file_size / 1024 / 1024).toFixed(2)} MB</TableCell>
                      <TableCell className="font-mono text-xs">{firmware.checksum.substring(0, 8)}...</TableCell>
                      <TableCell>{new Date(firmware.created_at).toLocaleDateString()}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(firmware.id, firmware.version)}
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Upload Dialog */}
        <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Upload Firmware</DialogTitle>
              <DialogDescription>
                Upload a new firmware file for OTA updates. Supported formats: .bin, .hex, .fw
              </DialogDescription>
            </DialogHeader>

            <form onSubmit={handleUploadSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="version">Version *</Label>
                <Input
                  id="version"
                  placeholder="e.g., 1.2.3"
                  value={uploadVersion}
                  onChange={(e) => setUploadVersion(e.target.value)}
                  required
                />
                <p className="text-sm text-muted-foreground">Semantic versioning recommended (e.g., 1.2.3)</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="file">Firmware File *</Label>
                <Input
                  id="file"
                  type="file"
                  accept=".bin,.hex,.fw"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  required
                />
                {uploadFile && (
                  <p className="text-sm text-muted-foreground">
                    Selected: {uploadFile.name} ({(uploadFile.size / 1024 / 1024).toFixed(2)} MB)
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description (Optional)</Label>
                <Input
                  id="description"
                  placeholder="e.g., Bug fixes and performance improvements"
                  value={uploadDescription}
                  onChange={(e) => setUploadDescription(e.target.value)}
                />
              </div>

              <Separator />

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setShowUploadDialog(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={!uploadFile || !uploadVersion || uploadMutation.isPending}>
                  {uploadMutation.isPending ? (
                    <>
                      <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="h-4 w-4 mr-2" />
                      Upload
                    </>
                  )}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        {/* Info Card */}
        <Card>
          <CardHeader>
            <CardTitle>How firmware updates work</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>1. Upload a firmware file via the &quot;Upload Firmware&quot; button (stored on S3).</p>
            <p>2. Trigger an update from the charger&apos;s page — server schedules a PENDING row.</p>
            <p>3. Server sends OCPP UpdateFirmware when the charger is online and idle. WebSocket is expected to drop during download.</p>
            <p>4. Completion is confirmed when the charger reboots and reports the new firmware version on BootNotification.</p>
            <p>5. If a retry is needed, the scheduler backs off exponentially: 5m → 30m → 2h → 4h, up to 5 attempts / ~6h total.</p>
            <p>6. For polling/out-of-network chargers, the &quot;Mark installed&quot; / &quot;Mark failed&quot; actions are how you close stuck rows.</p>
            <p className="mt-4 font-medium text-foreground">
              <AlertCircle className="inline h-4 w-4 mr-1" />
              Updates won&apos;t fire while the charger is offline or mid-transaction — the row stays PENDING until the charger is ready.
            </p>
          </CardContent>
        </Card>
      </div>
    </AdminOnly>
  );
}
