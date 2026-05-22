"use client";

import { FranchiseeOnly } from "@/components/RoleWrapper";
import { usePortalProfile } from "@/lib/queries/franchisee-portal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Building2,
  FileText,
  Percent,
  ShieldCheck,
  ExternalLink,
  CheckCircle2,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const STATUS_COLORS: Record<string, string> = {
  DRAFT: "bg-gray-100 text-gray-800",
  KYC_SUBMITTED: "bg-blue-100 text-blue-800",
  KYC_UNDER_REVIEW: "bg-yellow-100 text-yellow-800",
  KYC_NEEDS_CLARIFICATION: "bg-orange-100 text-orange-800",
  ACTIVE: "bg-green-100 text-green-800",
  SUSPENDED: "bg-red-100 text-red-800",
  DEACTIVATED: "bg-gray-300 text-gray-700",
};

function ProfileContent() {
  const { data, isLoading, error } = usePortalProfile();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
          <p className="text-muted-foreground mt-2">Loading profile...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">
            Failed to load profile
          </h2>
          <p className="text-gray-600">Please try refreshing the page.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Profile</h1>
        <Badge
          variant="secondary"
          className={STATUS_COLORS[data.status] || ""}
        >
          {data.status.replace(/_/g, " ")}
        </Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Business Info */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Business Info
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <InfoRow label="Business Name" value={data.business_name} />
            <InfoRow label="Business Type" value={data.business_type || "Not set"} />
            <InfoRow label="Contact Name" value={data.contact_name} />
            <InfoRow label="Contact Email" value={data.contact_email} />
            <InfoRow label="Contact Phone" value={data.contact_phone || "Not set"} />
            <InfoRow label="Address" value={data.address || "Not set"} />
            <InfoRow label="State" value={data.state || "Not set"} />
            <InfoRow label="Stations" value={String(data.station_count)} />
          </CardContent>
        </Card>

        {/* Tax / Legal */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Tax / Legal
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <InfoRow label="PAN Number" value={data.pan_number || "Not set"} />
            <InfoRow label="GSTIN" value={data.gstin || "Not set"} />
            <InfoRow label="State Code" value={data.state_code || "Not set"} />
          </CardContent>
        </Card>

        {/* Commission / TDS */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Percent className="h-5 w-5" />
              Commission / TDS
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <InfoRow
              label="Platform Commission"
              value={`${Number(data.commission_percent)}%`}
            />
            <InfoRow
              label="TDS Rate"
              value={`${Number(data.tds_rate_percent)}%`}
            />
          </CardContent>
        </Card>

        {/* KYC Status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" />
              KYC Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <InfoRow label="Status" value={data.status.replace(/_/g, " ")} />
            <InfoRow
              label="Razorpay Account"
              value={data.razorpay_account_id || "Not linked"}
            />
            {data.razorpay_account_status && (
              <InfoRow
                label="Account Status"
                value={data.razorpay_account_status}
              />
            )}
            <InfoRow
              label="KYC Verified At"
              value={
                data.kyc_verified_at
                  ? new Date(data.kyc_verified_at).toLocaleString()
                  : "Not verified"
              }
            />
            <KYCAction profile={data} />
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">
        Profile details are managed by the platform admin. Contact support for
        any changes.
      </p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-right">{value}</span>
    </div>
  );
}

/**
 * Renders the right call-to-action for the current KYC state.
 * - ACTIVE → green "KYC approved" banner, no action needed.
 * - KYC_SUBMITTED / KYC_UNDER_REVIEW / KYC_NEEDS_CLARIFICATION → open
 *   the Razorpay hosted onboarding page if we captured the URL,
 *   otherwise tell the user to check the email Razorpay sent them.
 * - DRAFT → admin hasn't kicked off onboarding yet.
 */
interface KYCProfile {
  status?: string;
  razorpay_onboarding_url?: string | null;
  razorpay_account_id?: string | null;
  contact_email?: string;
}

function KYCAction({ profile }: { profile: KYCProfile | null | undefined }) {
  const status: string = profile?.status ?? "";
  const url: string | null | undefined = profile?.razorpay_onboarding_url;

  if (status === "ACTIVE") {
    return (
      <div className="flex items-center gap-2 border-t pt-3 mt-3 text-sm text-green-700">
        <CheckCircle2 className="h-4 w-4" />
        <span>KYC approved — settlements will flow to your linked account.</span>
      </div>
    );
  }

  if (status === "DRAFT" && !profile?.razorpay_account_id) {
    return (
      <p className="text-sm text-muted-foreground border-t pt-3 mt-3">
        KYC not started. Your admin needs to kick off Razorpay onboarding —
        contact them if this has been pending.
      </p>
    );
  }

  const needsAction =
    status === "KYC_SUBMITTED" ||
    status === "KYC_UNDER_REVIEW" ||
    status === "KYC_NEEDS_CLARIFICATION";

  if (!needsAction) return null;

  if (url) {
    return (
      <div className="border-t pt-3 mt-3 space-y-2">
        <Button asChild size="sm" className="w-full">
          <a href={url} target="_blank" rel="noopener noreferrer">
            <ExternalLink className="h-4 w-4 mr-2" />
            Complete KYC on Razorpay
          </a>
        </Button>
        <p className="text-xs text-muted-foreground">
          Opens Razorpay&apos;s hosted onboarding. Finish all steps there; your
          status here updates automatically once Razorpay confirms.
        </p>
      </div>
    );
  }

  return (
    <p className="text-sm text-muted-foreground border-t pt-3 mt-3">
      Razorpay has emailed a KYC onboarding link to{" "}
      <span className="font-medium">{profile?.contact_email}</span>. Check
      your inbox (and spam) to complete verification.
    </p>
  );
}

export default function ProfilePage() {
  return (
    <FranchiseeOnly
      fallback={
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">
              Access Denied
            </h2>
            <p className="text-gray-600 mb-4">
              You need franchisee privileges to access this page.
            </p>
            <Link
              href="/dashboard"
              className="text-blue-600 hover:text-blue-800"
            >
              Go to Dashboard
            </Link>
          </div>
        </div>
      }
    >
      <ProfileContent />
    </FranchiseeOnly>
  );
}
