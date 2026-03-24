"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Search,
  Zap,
  Clock,
  IndianRupee,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { usePublicQRTransactions } from "@/lib/queries/public-qr-transactions";
import { publicQRTransactionService, QRTransactionItem } from "@/lib/api-services";

const STATUS_OPTIONS = [
  { value: "ALL", label: "All Statuses" },
  { value: "COMPLETED", label: "Completed" },
  { value: "REFUNDED", label: "Refunded" },
  { value: "CHARGING", label: "Charging" },
  { value: "PAID", label: "Paid" },
  { value: "FAILED", label: "Failed" },
  { value: "REFUND_FAILED", label: "Refund Failed" },
  { value: "EXPIRED", label: "Expired" },
];

type Step = "idle" | "looking_up" | "verify" | "verifying" | "verified";

function getStatusBadgeClass(status: string) {
  switch (status) {
    case "COMPLETED":
      return "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
    case "CHARGING":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
    case "PAID":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400";
    case "REFUNDED":
      return "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400";
    case "FAILED":
    case "REFUND_FAILED":
      return "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
    case "EXPIRED":
      return "bg-gray-100 text-gray-800 dark:bg-gray-900/20 dark:text-gray-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatTime(isoString: string): string {
  return new Date(isoString).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatINR(val: string | null): string | null {
  if (!val) return null;
  const num = parseFloat(val);
  return isNaN(num) ? val : num.toFixed(2);
}

function getErrorMessage(error: Error): string {
  const msg = error.message;
  if (msg.includes("429")) return "Too many requests. Please wait a moment and try again.";
  if (msg.includes("403")) return "Name does not match. Please try again.";
  if (msg.includes("404")) return "No transactions found for this UPI ID.";
  if (msg.includes("401")) return "Session expired. Please verify again.";
  if (msg.includes("400")) return "Please enter a valid UPI ID (e.g. name@bank)";
  if (msg.includes("503")) return "Payment service unavailable. Please try later.";
  if (msg.includes("500")) return "Server error. Please try again later.";
  return "Something went wrong. Please try again.";
}

function TransactionCard({ txn }: { txn: QRTransactionItem }) {
  return (
    <Card className="border-0 shadow-md bg-card">
      <CardContent className="p-4 space-y-3">
        <div className="flex justify-between items-start">
          <div>
            <p className="text-sm font-medium text-card-foreground">
              {formatDate(txn.created_at)}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatTime(txn.created_at)}
            </p>
          </div>
          <Badge className={`border-0 ${getStatusBadgeClass(txn.status)}`}>
            {txn.status.replace("_", " ")}
          </Badge>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <IndianRupee className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Paid</p>
              <p className="font-semibold text-card-foreground">
                {formatINR(txn.amount_paid)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 p-2 bg-muted/50 rounded-lg">
            <Zap className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-xs text-muted-foreground">Energy</p>
              <p className="font-semibold text-card-foreground">
                {txn.energy_consumed_kwh != null
                  ? `${txn.energy_consumed_kwh.toFixed(2)} kWh`
                  : "N/A"}
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {txn.duration_minutes != null && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>{formatDuration(txn.duration_minutes)}</span>
            </div>
          )}
          {txn.charger_name && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground truncate">
              <Zap className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="truncate">{txn.charger_name}</span>
            </div>
          )}
        </div>

        {txn.energy_cost && (
          <div className="border-t border-border pt-2 space-y-1 text-sm">
            <div className="flex justify-between text-muted-foreground">
              <span>Energy cost</span>
              <span>{formatINR(txn.energy_cost)}</span>
            </div>
            {txn.platform_fee && (
              <div className="flex justify-between text-muted-foreground">
                <span>Platform fee</span>
                <span>{formatINR(txn.platform_fee)}</span>
              </div>
            )}
          </div>
        )}

        {txn.refund_amount && (
          <div className="flex items-center gap-2 p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-700 rounded-lg">
            <RefreshCw className="h-4 w-4 text-purple-600 dark:text-purple-400" />
            <span className="text-sm font-medium text-purple-800 dark:text-purple-300">
              Refunded: {formatINR(txn.refund_amount)}
            </span>
          </div>
        )}

        {txn.failure_reason &&
          (txn.status === "FAILED" || txn.status === "REFUND_FAILED") && (
            <div className="flex items-start gap-2 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg">
              <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
              <span className="text-sm text-red-800 dark:text-red-300">
                {txn.failure_reason}
              </span>
            </div>
          )}
      </CardContent>
    </Card>
  );
}

export default function MyChargesPage() {
  const [vpaInput, setVpaInput] = useState("");
  const [nameInput, setNameInput] = useState("");
  const [step, setStep] = useState<Step>("idle");
  const [maskedName, setMaskedName] = useState("");
  const [verifiedVpa, setVerifiedVpa] = useState("");
  const [token, setToken] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const limit = 10;

  const { data, isLoading, error } = usePublicQRTransactions({
    token,
    page: currentPage,
    limit,
    status: statusFilter !== "ALL" ? statusFilter : undefined,
  });

  const totalPages = data ? Math.ceil(data.total / limit) : 1;

  const handleLookup = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = vpaInput.trim().toLowerCase();
    if (!trimmed) return;

    setErrorMsg("");
    setStep("looking_up");

    try {
      const result = await publicQRTransactionService.lookup(trimmed);
      setMaskedName(result.masked_name);
      setVerifiedVpa(trimmed);
      setStep("verify");
    } catch (err) {
      setErrorMsg(getErrorMessage(err as Error));
      setStep("idle");
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nameInput.trim()) return;

    setErrorMsg("");
    setStep("verifying");

    try {
      const result = await publicQRTransactionService.verify(verifiedVpa, nameInput.trim());
      setToken(result.token);
      setCurrentPage(1);
      setStep("verified");
    } catch (err) {
      setErrorMsg(getErrorMessage(err as Error));
      setStep("verify");
    }
  };

  const handleReset = () => {
    setStep("idle");
    setVpaInput("");
    setNameInput("");
    setMaskedName("");
    setVerifiedVpa("");
    setToken("");
    setErrorMsg("");
    setStatusFilter("ALL");
    setCurrentPage(1);
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="px-4 py-6 space-y-6 max-w-md mx-auto">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-foreground">
            Transaction History
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Enter your UPI ID to view your QR charging transactions
          </p>
        </div>

        {/* Error display */}
        {errorMsg && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 p-4 rounded-lg text-center">
            <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mx-auto mb-2" />
            <p className="text-sm text-red-800 dark:text-red-300">{errorMsg}</p>
          </div>
        )}

        {/* Step 1: Enter VPA */}
        {(step === "idle" || step === "looking_up") && (
          <form onSubmit={handleLookup} className="space-y-3">
            <div className="flex gap-2">
              <Input
                type="text"
                placeholder="your-upi@bank"
                value={vpaInput}
                onChange={(e) => setVpaInput(e.target.value)}
                className="flex-1"
                disabled={step === "looking_up"}
              />
              <Button type="submit" disabled={!vpaInput.trim() || step === "looking_up"}>
                {step === "looking_up" ? (
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
              </Button>
            </div>
          </form>
        )}

        {/* Step 2: Verify name */}
        {(step === "verify" || step === "verifying") && (
          <Card className="border-0 shadow-lg bg-card">
            <CardContent className="p-4 space-y-4">
              <div className="flex items-center gap-2 text-card-foreground">
                <ShieldCheck className="h-5 w-5 text-primary" />
                <span className="font-medium">Verify your identity</span>
              </div>
              <p className="text-sm text-muted-foreground">
                Account found for <span className="font-semibold text-card-foreground">{maskedName}</span>.
                Enter the full name registered with your UPI ID to continue.
              </p>
              <form onSubmit={handleVerify} className="space-y-3">
                <Input
                  type="text"
                  placeholder="Enter your full name"
                  value={nameInput}
                  onChange={(e) => { setNameInput(e.target.value); setErrorMsg(""); }}
                  disabled={step === "verifying"}
                  autoFocus
                />
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleReset}
                    className="flex-1"
                    disabled={step === "verifying"}
                  >
                    Back
                  </Button>
                  <Button
                    type="submit"
                    className="flex-1"
                    disabled={!nameInput.trim() || step === "verifying"}
                  >
                    {step === "verifying" ? "Verifying..." : "Verify"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Verified — show transactions */}
        {step === "verified" && (
          <>
            {/* Verified badge + change VPA */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
                <ShieldCheck className="h-4 w-4" />
                <span>Verified: {verifiedVpa}</span>
              </div>
              <Button variant="ghost" size="sm" onClick={handleReset}>
                Change
              </Button>
            </div>

            {/* Status filter */}
            <Select value={statusFilter} onValueChange={(val) => {
              setStatusFilter(val);
              setCurrentPage(1);
            }}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Loading */}
            {isLoading && (
              <div className="text-center py-12">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary mx-auto" />
                <p className="text-muted-foreground mt-4">Loading transactions...</p>
              </div>
            )}

            {/* Query error (e.g., token expired) */}
            {error && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 p-4 rounded-lg text-center">
                <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400 mx-auto mb-2" />
                <p className="text-sm text-red-800 dark:text-red-300">
                  {getErrorMessage(error)}
                </p>
                {error.message.includes("401") && (
                  <Button variant="outline" size="sm" className="mt-3" onClick={handleReset}>
                    Verify again
                  </Button>
                )}
              </div>
            )}

            {/* Results */}
            {data && !isLoading && (
              <>
                <p className="text-sm text-muted-foreground">
                  {data.total === 0
                    ? "No transactions found"
                    : `${data.total} transaction${data.total !== 1 ? "s" : ""} found`}
                </p>

                <div className="space-y-3">
                  {data.data.map((txn) => (
                    <TransactionCard key={txn.id} txn={txn} />
                  ))}
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage <= 1}
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft className="h-4 w-4 mr-1" />
                      Prev
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      Page {currentPage} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={currentPage >= totalPages}
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    >
                      Next
                      <ChevronRight className="h-4 w-4 ml-1" />
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Initial state */}
        {step === "idle" && !errorMsg && (
          <div className="text-center py-12">
            <Zap className="h-12 w-12 text-muted-foreground/40 mx-auto mb-4" />
            <p className="text-muted-foreground">
              Enter your UPI ID above to look up your charging history
            </p>
          </div>
        )}

        <div className="h-6" />
      </div>
    </div>
  );
}
