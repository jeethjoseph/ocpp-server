"use client";

import { Button } from "@/components/ui/button";
import { AlertCircle, RefreshCw } from "lucide-react";

export function ActiveSessionsError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg">
      <div className="flex items-start gap-2">
        <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1 space-y-2">
          <p className="text-sm text-red-800 dark:text-red-300">
            Couldn&apos;t load your active session — we&apos;ll keep trying.
            Your charging is unaffected.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={onRetry}
          >
            <RefreshCw className="h-3 w-3 mr-1.5" />
            Retry now
          </Button>
        </div>
      </div>
    </div>
  );
}
