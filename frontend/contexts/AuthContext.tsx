'use client';

import { createContext, useContext, ReactNode, useEffect, useRef } from 'react';
import { useAuth as useClerkAuth, useUser } from '@clerk/nextjs';

interface AuthContextValue {
  isLoaded: boolean;
  isSignedIn: boolean;
  userId: string | null;
  getToken: () => Promise<string | null>;
  user?: {
    id: string;
    role?: string;
    email?: string;
  } | null;
  isAuthReady: boolean; // New flag to indicate auth is fully ready
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Global reference for getToken to be used outside React components
let globalGetToken: (() => Promise<string | null>) | null = null;
let globalAuthReady = false;

export function setGlobalGetToken(getToken: () => Promise<string | null>) {
  globalGetToken = getToken;
}

export function getGlobalGetToken(): (() => Promise<string | null>) | null {
  return globalGetToken;
}

export function setGlobalAuthReady(ready: boolean) {
  globalAuthReady = ready;
}

export function isGlobalAuthReady(): boolean {
  return globalAuthReady;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const clerkAuth = useClerkAuth();
  const { user: clerkUser, isLoaded: userLoaded } = useUser();

  // Use refs to ensure getToken always accesses current auth state (not stale closure values)
  const clerkAuthRef = useRef(clerkAuth);

  // Update ref on every render to always have current value
  clerkAuthRef.current = clerkAuth;

  const getToken = async (): Promise<string | null> => {
    // Use ref to get CURRENT auth state (not captured closure value)
    const currentAuth = clerkAuthRef.current;

    if (!currentAuth.isLoaded) {
      console.warn('⚠️ Auth not loaded yet - query should not have run');
      return null;
    }

    if (!currentAuth.isSignedIn) {
      console.warn('⚠️ User not signed in');
      return null;
    }

    try {
      const token = await currentAuth.getToken();
      return token;
    } catch (error) {
      console.error('❌ Failed to get auth token:', error);
      return null;
    }
  };

  // Determine if auth is fully ready (loaded and has user info)
  const isAuthReady = clerkAuth.isLoaded && userLoaded;

  // Set the global getToken reference when auth state changes
  // Since getToken uses refs internally, it always accesses current auth state
  // so we only need to update when isAuthReady changes, not on every render
  useEffect(() => {
    setGlobalGetToken(getToken);
    setGlobalAuthReady(isAuthReady);
  }, [isAuthReady, getToken]);

  // Map Clerk user to our auth abstraction format
  const user = clerkUser ? {
    id: clerkUser.id,
    role: clerkUser.publicMetadata?.role as string | undefined,
    email: clerkUser.primaryEmailAddress?.emailAddress,
  } : null;

  const value: AuthContextValue = {
    isLoaded: clerkAuth.isLoaded && userLoaded,
    isSignedIn: clerkAuth.isSignedIn ?? false,
    userId: clerkAuth.userId ?? null,
    getToken,
    user,
    isAuthReady,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
