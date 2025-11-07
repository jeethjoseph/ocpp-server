"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { walletPaymentService } from "@/lib/api-services";
import { Loader2 } from "lucide-react";

// Declare Razorpay types
interface RazorpayPaymentResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: (response: RazorpayPaymentResponse) => void;
  prefill: {
    name: string;
    email: string;
    contact: string;
  };
  theme: {
    color: string;
  };
  modal: {
    ondismiss: () => void;
  };
}

interface RazorpayInstance {
  open: () => void;
}

declare global {
  interface Window {
    Razorpay: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

interface WalletRechargeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function WalletRechargeModal({
  open,
  onOpenChange,
  onSuccess,
}: WalletRechargeModalProps) {
  const [amount, setAmount] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);

  const handleAmountChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    // Allow only numbers and decimal point
    if (value === "" || /^\d*\.?\d*$/.test(value)) {
      setAmount(value);
    }
  };

  const handleQuickAmount = (value: number) => {
    setAmount(value.toString());
  };

  const handleRecharge = async () => {
    const rechargeAmount = parseFloat(amount);

    if (!amount || rechargeAmount <= 0) {
      toast.error("Please enter a valid amount");
      return;
    }

    if (rechargeAmount < 1) {
      toast.error("Minimum recharge amount is ₹1");
      return;
    }

    if (rechargeAmount > 100000) {
      toast.error("Maximum recharge amount is ₹1,00,000");
      return;
    }

    setIsLoading(true);

    try {
      // Step 1: Create order on backend
      const orderResponse = await walletPaymentService.createRechargeOrder(
        rechargeAmount
      );

      // Step 2: Load Razorpay script if not already loaded
      if (!window.Razorpay) {
        const script = document.createElement("script");
        script.src = "https://checkout.razorpay.com/v1/checkout.js";
        script.async = true;
        document.body.appendChild(script);

        // Wait for script to load
        await new Promise<void>((resolve, reject) => {
          script.onload = () => resolve();
          script.onerror = () => reject(new Error("Failed to load Razorpay"));
        });
      }

      // Step 3: Open Razorpay checkout
      const options = {
        key: orderResponse.key_id,
        amount: orderResponse.amount * 100, // Amount in paise
        currency: orderResponse.currency,
        name: "OCPP CSMS",
        description: `Wallet Recharge - ₹${orderResponse.amount}`,
        order_id: orderResponse.order_id,
        handler: async function (response: RazorpayPaymentResponse) {
          // Payment successful - verify on backend
          try {
            const verifyResponse =
              await walletPaymentService.verifyPayment({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              });

            if (verifyResponse.success) {
              toast.success(
                `₹${orderResponse.amount} added to wallet! New balance: ₹${verifyResponse.wallet_balance}`
              );
              setAmount("");
              onOpenChange(false);
              onSuccess?.();
            } else {
              toast.error("Payment verification failed. Please contact support.");
            }
          } catch (error: unknown) {
            console.error("Payment verification error:", error);
            const errorMessage = error instanceof Error && 'response' in error &&
              typeof error.response === 'object' && error.response !== null &&
              'data' in error.response &&
              typeof error.response.data === 'object' && error.response.data !== null &&
              'detail' in error.response.data
              ? String(error.response.data.detail)
              : "Payment verification failed. Your wallet will be updated shortly via webhook.";
            toast.error(errorMessage);
            // Close modal anyway as webhook will handle it
            onOpenChange(false);
            onSuccess?.();
          } finally {
            setIsLoading(false);
          }
        },
        prefill: {
          name: "",
          email: "",
          contact: "",
        },
        theme: {
          color: "#3399cc",
        },
        modal: {
          ondismiss: function () {
            setIsLoading(false);
            toast.info("Payment cancelled");
          },
        },
      };

      const razorpay = new window.Razorpay(options);
      razorpay.open();
    } catch (error: unknown) {
      console.error("Recharge error:", error);
      const errorMessage = error instanceof Error && 'response' in error &&
        typeof error.response === 'object' && error.response !== null &&
        'data' in error.response &&
        typeof error.response.data === 'object' && error.response.data !== null &&
        'detail' in error.response.data
        ? String(error.response.data.detail)
        : "Failed to initiate recharge. Please try again.";
      toast.error(errorMessage);
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Recharge Wallet</DialogTitle>
          <DialogDescription>
            Add money to your wallet for charging sessions
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Amount Input */}
          <div className="grid gap-2">
            <Label htmlFor="amount">Amount (₹)</Label>
            <Input
              id="amount"
              type="text"
              inputMode="decimal"
              placeholder="Enter amount"
              value={amount}
              onChange={handleAmountChange}
              disabled={isLoading}
            />
            <p className="text-sm text-muted-foreground">
              Min: ₹1 | Max: ₹1,00,000
            </p>
          </div>

          {/* Quick Amount Buttons */}
          <div className="grid gap-2">
            <Label>Quick Amount</Label>
            <div className="grid grid-cols-4 gap-2">
              {[100, 200, 500, 1000].map((value) => (
                <Button
                  key={value}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handleQuickAmount(value)}
                  disabled={isLoading}
                >
                  ₹{value}
                </Button>
              ))}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleRecharge}
            disabled={isLoading || !amount || parseFloat(amount) <= 0}
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Processing...
              </>
            ) : (
              `Recharge ₹${amount || "0"}`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
