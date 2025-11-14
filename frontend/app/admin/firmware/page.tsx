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
} from "@/lib/queries/firmware";
import { Upload, Trash2, RefreshCw, AlertCircle, CheckCircle2, Clock, Download, XCircle } from "lucide-react";
import { useAuth } from "@clerk/nextjs";

export default function AdminFirmwarePage() {
  const { getToken } = useAuth();
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadVersion, setUploadVersion] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");

  // Queries
  const { data: firmwareData, isLoading: isLoadingFirmware } = useFirmwareFiles({ is_active: true });
  const { data: statusData } = useUpdateStatus();

  // Mutations
  const uploadMutation = useUploadFirmware();
  const deleteMutation = useDeleteFirmware();

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

  const handleDelete = async (firmwareId: number, version: string) => {
    if (confirm(`Are you sure you want to delete firmware version ${version}?`)) {
      await deleteMutation.mutateAsync(firmwareId);
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; icon: React.ReactElement }> = {
      PENDING: { variant: "secondary", icon: <Clock className="h-3 w-3" /> },
      DOWNLOADING: { variant: "default", icon: <Download className="h-3 w-3" /> },
      DOWNLOADED: { variant: "default", icon: <CheckCircle2 className="h-3 w-3" /> },
      INSTALLING: { variant: "default", icon: <RefreshCw className="h-3 w-3 animate-spin" /> },
      INSTALLED: { variant: "outline", icon: <CheckCircle2 className="h-3 w-3" /> },
      DOWNLOAD_FAILED: { variant: "destructive", icon: <XCircle className="h-3 w-3" /> },
      INSTALLATION_FAILED: { variant: "destructive", icon: <AlertCircle className="h-3 w-3" /> },
    };

    const { variant, icon } = variants[status] || { variant: "secondary" as const, icon: <Clock className="h-3 w-3" /> };

    return (
      <Badge variant={variant} className="flex items-center gap-1">
        {icon}
        {status.replace(/_/g, " ")}
      </Badge>
    );
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
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Pending</CardDescription>
                <CardTitle className="text-2xl">{summary.pending}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Downloading</CardDescription>
                <CardTitle className="text-2xl">{summary.downloading}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Installing</CardDescription>
                <CardTitle className="text-2xl">{summary.installing}</CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Completed Today</CardDescription>
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
              <CardDescription>Real-time monitoring of ongoing firmware updates</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Charger</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inProgressUpdates.map((update) => (
                    <TableRow key={update.update_id}>
                      <TableCell>
                        <div>
                          <div className="font-medium">{update.charger_name}</div>
                          <div className="text-sm text-muted-foreground">{update.charge_point_id}</div>
                        </div>
                      </TableCell>
                      <TableCell>{update.firmware_version}</TableCell>
                      <TableCell>{getStatusBadge(update.status)}</TableCell>
                      <TableCell>
                        {update.started_at
                          ? new Date(update.started_at).toLocaleString()
                          : new Date(update.initiated_at).toLocaleString()}
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
            <CardTitle>How to Update Chargers</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>1. Upload a firmware file using the &quot;Upload Firmware&quot; button above</p>
            <p>2. Go to the Chargers page to select chargers for update</p>
            <p>3. Click on a charger and use the &quot;Update Firmware&quot; button</p>
            <p>4. Monitor update progress here in the &quot;Active Updates&quot; section</p>
            <p className="mt-4 font-medium text-foreground">
              <AlertCircle className="inline h-4 w-4 mr-1" />
              Updates will only trigger if charger is online and not actively charging
            </p>
          </CardContent>
        </Card>
      </div>
    </AdminOnly>
  );
}
