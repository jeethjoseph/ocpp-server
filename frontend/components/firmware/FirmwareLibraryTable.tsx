"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Trash2, ChevronRight, ChevronDown, Rocket } from "lucide-react";
import type { FirmwareFile } from "@/types/api";

interface FirmwareLibraryTableProps {
  firmwareFiles: FirmwareFile[];
  onDelete: (firmwareId: number, version: string) => void;
  onDeploy?: (firmware: FirmwareFile) => void;
  isDeleting?: boolean;
}

/**
 * Firmware Library table. The `description` (release notes) admins enter at
 * upload time is surfaced in an expandable detail row toggled per firmware
 * version, keeping the table itself lean. Rows without a description show no
 * expand affordance.
 */
export function FirmwareLibraryTable({ firmwareFiles, onDelete, onDeploy, isDeleting }: FirmwareLibraryTableProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const toggle = (id: number) => setExpandedId((cur) => (cur === id ? null : id));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8" />
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
        {firmwareFiles.map((firmware) => {
          const hasDescription = Boolean(firmware.description?.trim());
          const isExpanded = expandedId === firmware.id;
          return (
            <React.Fragment key={firmware.id}>
              <TableRow>
                <TableCell>
                  {hasDescription && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0"
                      aria-label={isExpanded ? "Hide release notes" : "Show release notes"}
                      aria-expanded={isExpanded}
                      onClick={() => toggle(firmware.id)}
                    >
                      {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </Button>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">#{firmware.id}</TableCell>
                <TableCell className="font-medium">{firmware.version}</TableCell>
                <TableCell>{firmware.filename}</TableCell>
                <TableCell>{(firmware.file_size / 1024 / 1024).toFixed(2)} MB</TableCell>
                <TableCell className="font-mono text-xs">{firmware.checksum.substring(0, 8)}...</TableCell>
                <TableCell>{new Date(firmware.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {onDeploy && (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="Deploy to chargers"
                        aria-label={`Deploy ${firmware.version} to chargers`}
                        onClick={() => onDeploy(firmware)}
                      >
                        <Rocket className="h-4 w-4" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onDelete(firmware.id, firmware.version)}
                      disabled={isDeleting}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
              {isExpanded && hasDescription && (
                <TableRow>
                  <TableCell colSpan={8} className="bg-muted/40">
                    <div className="py-1">
                      <div className="text-xs font-medium text-muted-foreground mb-1">Release notes</div>
                      <p className="text-sm whitespace-pre-wrap break-words max-w-3xl">{firmware.description}</p>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </React.Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
