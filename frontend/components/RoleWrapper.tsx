"use client";

import { useUser } from "@clerk/nextjs";
import { useEffect, useState } from "react";

interface RoleWrapperProps {
  children: React.ReactNode;
  allowedRoles?: string[];
  fallback?: React.ReactNode;
}

export function RoleWrapper({ 
  children, 
  allowedRoles = ["USER", "ADMIN"], 
  fallback = <div>Access denied</div> 
}: RoleWrapperProps) {
  const { user, isLoaded } = useUser();

  // Show loading while Clerk is loading
  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center p-4">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <span className="ml-2">Loading...</span>
      </div>
    );
  }

  // Get user role - no fallback for security
  const userRole = user?.publicMetadata?.role as string;
  
  // Check if user has required role
  if (allowedRoles.includes(userRole)) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}

// Hook to get current user role
export function useUserRole() {
  const { user, isLoaded } = useUser();
  
  return {
    role: user?.publicMetadata?.role as string | undefined,
    isAdmin: user?.publicMetadata?.role === "ADMIN",
    isUser: user?.publicMetadata?.role === "USER",
    isLoaded,
    user
  };
}

// Component for admin-only content
export function AdminOnly({ children, fallback = null }: { 
  children: React.ReactNode; 
  fallback?: React.ReactNode;
}) {
  return (
    <RoleWrapper allowedRoles={["ADMIN"]} fallback={fallback}>
      {children}
    </RoleWrapper>
  );
}

// Component for user-only content (excluding admins)
export function UserOnly({ children, fallback = null }: { 
  children: React.ReactNode; 
  fallback?: React.ReactNode;
}) {
  return (
    <RoleWrapper allowedRoles={["USER"]} fallback={fallback}>
      {children}
    </RoleWrapper>
  );
}

// Component for authenticated users (both USER and ADMIN)
export function AuthenticatedOnly({ children, fallback = null }: { 
  children: React.ReactNode; 
  fallback?: React.ReactNode;
}) {
  return (
    <RoleWrapper allowedRoles={["USER", "ADMIN"]} fallback={fallback}>
      {children}
    </RoleWrapper>
  );
}