"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AdminOnly } from "@/components/RoleWrapper";
import {
  QrCode,
  Download,
  Printer,
  ArrowLeft,
  CreditCard,
  X,
} from "lucide-react";
import Link from "next/link";
import { useQRCode, useQRPayments, useCloseQRCode } from "@/lib/queries/qr-codes";
import type { QRPaymentStatus } from "@/types/api";

function getStatusBadge(status: QRPaymentStatus, belowMinimum?: boolean) {
  // A REFUND_FAILED row that only failed Razorpay's sub-₹1 floor is benign —
  // show a neutral badge so it doesn't read as an operational failure.
  if (status === "REFUND_FAILED" && belowMinimum) {
    return <Badge variant="secondary">No refund · below ₹1</Badge>;
  }
  const variants: Record<QRPaymentStatus, "default" | "secondary" | "destructive" | "outline"> = {
    PAID: "default",
    CHARGING: "default",
    COMPLETED: "secondary",
    REFUNDED: "secondary",
    REFUND_FAILED: "destructive",
    EXPIRED: "outline",
    FAILED: "destructive",
  };
  return <Badge variant={variants[status] || "outline"}>{status}</Badge>;
}

function getRefundSpeedBadge(speed?: string | null) {
  if (!speed) return null;
  if (speed === "instant") {
    return (
      <Badge
        variant="outline"
        className="bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400 border-transparent"
      >
        Instant
      </Badge>
    );
  }
  return (
    <Badge variant="secondary">
      Normal (5-7 days)
    </Badge>
  );
}

export default function QRCodeDetailPage() {
  const params = useParams();
  const qrId = parseInt(params.id as string);
  const [paymentsPage, setPaymentsPage] = useState(1);

  const { data: qrCode, isLoading } = useQRCode(qrId);
  const { data: paymentsData } = useQRPayments(qrId, {
    page: paymentsPage,
    limit: 20,
  });
  const closeMutation = useCloseQRCode();

  const handleDownloadQR = () => {
    if (!qrCode?.image_url) return;
    const link = document.createElement("a");
    link.href = qrCode.image_url;
    link.download = `qr-code-${qrCode.charger_name || qrCode.id}.png`;
    link.target = "_blank";
    link.click();
  };

  const handlePrintQR = () => {
    if (!qrCode?.image_url) return;
    const printWindow = window.open("", "_blank");
    if (printWindow) {
      printWindow.document.write(`
        <html>
          <head><title>QR Code - ${qrCode.charger_name}</title></head>
          <body style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:sans-serif;">
            <h2>${qrCode.charger_name}</h2>
            <p style="color:#666;">${qrCode.charge_point_string_id}</p>
            <img src="${qrCode.image_url}" style="max-width:400px;margin:20px 0;" />
            <p style="color:#666;">Scan to pay for EV charging</p>
          </body>
        </html>
      `);
      printWindow.document.close();
      printWindow.print();
    }
  };

  if (isLoading) {
    return (
      <AdminOnly>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="text-center py-8 text-muted-foreground">
            Loading...
          </div>
        </div>
      </AdminOnly>
    );
  }

  if (!qrCode) {
    return (
      <AdminOnly>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="text-center py-8 text-muted-foreground">
            QR code not found.
          </div>
        </div>
      </AdminOnly>
    );
  }

  const paymentsTotalPages = paymentsData
    ? Math.ceil(paymentsData.total / 20)
    : 0;

  return (
    <AdminOnly>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/admin/qr-codes">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-4 w-4 mr-1" />
              Back
            </Button>
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-card-foreground">
              {qrCode.charger_name} - QR Code
            </h1>
            <p className="text-muted-foreground">
              {qrCode.charge_point_string_id}
            </p>
          </div>
          <Badge variant={qrCode.is_active ? "default" : "destructive"} className="text-sm">
            {qrCode.is_active ? "Active" : "Inactive"}
          </Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* QR Code Image Card */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <QrCode className="h-5 w-5" />
                QR Code
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-4">
              {qrCode.image_url ? (
                <img
                  src={qrCode.image_url}
                  alt="Payment QR Code"
                  className="w-64 h-64 border rounded-lg"
                />
              ) : (
                <div className="w-64 h-64 border rounded-lg flex items-center justify-center text-muted-foreground">
                  No QR image available
                </div>
              )}
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={handleDownloadQR}>
                  <Download className="h-4 w-4 mr-1" />
                  Download
                </Button>
                <Button variant="outline" size="sm" onClick={handlePrintQR}>
                  <Printer className="h-4 w-4 mr-1" />
                  Print
                </Button>
                {qrCode.is_active && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => closeMutation.mutate(qrCode.id)}
                    disabled={closeMutation.isPending}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Close
                  </Button>
                )}
              </div>
              <div className="text-xs text-muted-foreground text-center space-y-1">
                <p>Razorpay QR: {qrCode.razorpay_qr_code_id}</p>
                <p>
                  Created: {new Date(qrCode.created_at).toLocaleDateString()}
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Stats Cards */}
          <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">
                  {qrCode.payment_count ?? 0}
                </div>
                <p className="text-sm text-muted-foreground">Total Payments</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">
                  {qrCode.total_revenue
                    ? `₹${Number(qrCode.total_revenue).toFixed(2)}`
                    : "₹0.00"}
                </div>
                <p className="text-sm text-muted-foreground">Total Revenue</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">
                  {qrCode.total_refunds
                    ? `₹${Number(qrCode.total_refunds).toFixed(2)}`
                    : "₹0.00"}
                </div>
                <p className="text-sm text-muted-foreground">Total Refunds</p>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Payments Table */}
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              Payment History
              {paymentsData && ` (${paymentsData.total})`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!paymentsData?.data.length ? (
              <div className="text-center py-8 text-muted-foreground">
                No payments yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-3 px-2 font-medium">ID</th>
                      <th className="text-left py-3 px-2 font-medium">Date</th>
                      <th className="text-right py-3 px-2 font-medium">
                        Amount
                      </th>
                      <th className="text-left py-3 px-2 font-medium">
                        Customer VPA
                      </th>
                      <th className="text-right py-3 px-2 font-medium">
                        Energy Cost
                      </th>
                      <th className="text-right py-3 px-2 font-medium">
                        GST
                      </th>
                      <th className="text-right py-3 px-2 font-medium">
                        Platform Fee
                      </th>
                      <th className="text-right py-3 px-2 font-medium">
                        Refund
                      </th>
                      <th className="text-left py-3 px-2 font-medium">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {paymentsData.data.map((payment) => (
                      <tr
                        key={payment.id}
                        className="border-b hover:bg-accent/50"
                      >
                        <td className="py-3 px-2 font-mono text-xs text-muted-foreground">
                          #{payment.id}
                        </td>
                        <td className="py-3 px-2 text-muted-foreground">
                          {new Date(payment.created_at).toLocaleString()}
                        </td>
                        <td className="py-3 px-2 text-right font-medium">
                          ₹{Number(payment.amount_paid).toFixed(2)}
                        </td>
                        <td className="py-3 px-2 font-mono text-xs">
                          {payment.customer_vpa || "-"}
                        </td>
                        <td className="py-3 px-2 text-right">
                          {payment.energy_cost
                            ? `₹${Number(payment.energy_cost).toFixed(2)}`
                            : "-"}
                        </td>
                        <td className="py-3 px-2 text-right">
                          {payment.gst_amount
                            ? `₹${Number(payment.gst_amount).toFixed(2)}`
                            : "-"}
                        </td>
                        <td className="py-3 px-2 text-right">
                          {payment.platform_fee
                            ? <span title={payment.fee_source === 'estimated' ? 'Estimated (2%)' : `Commission: ₹${Number(payment.razorpay_commission || 0).toFixed(2)} + GST: ₹${Number(payment.razorpay_gst || 0).toFixed(2)}`}>
                                {`₹${Number(payment.platform_fee).toFixed(2)}`}
                                {payment.fee_source === 'estimated' && <span className="text-xs text-muted-foreground ml-1">(est.)</span>}
                              </span>
                            : "-"}
                        </td>
                        <td className="py-3 px-2 text-right">
                          {payment.refund_amount ? (
                            <div className="flex items-center justify-end gap-1.5">
                              <span>{`₹${Number(payment.refund_amount).toFixed(2)}`}</span>
                              {getRefundSpeedBadge(payment.razorpay_refund_speed_processed)}
                            </div>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td className="py-3 px-2">
                          {getStatusBadge(payment.status, payment.refund_below_minimum)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {paymentsTotalPages > 1 && (
              <div className="flex justify-between items-center mt-4">
                <p className="text-sm text-muted-foreground">
                  Page {paymentsPage} of {paymentsTotalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPaymentsPage((p) => Math.max(1, p - 1))
                    }
                    disabled={paymentsPage === 1}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPaymentsPage((p) =>
                        Math.min(paymentsTotalPages, p + 1)
                      )
                    }
                    disabled={paymentsPage === paymentsTotalPages}
                  >
                    Next
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
