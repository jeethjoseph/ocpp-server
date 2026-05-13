"use client";

import {
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-client";

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000 * 60, // 1 minute
            gcTime: 1000 * 60 * 5, // 5 minutes
            retry: 2,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: 1,
          },
        },
        // Defence-in-depth: backend enforces tenant isolation on
        // /api/franchisee/*. If a portal query gets 403/404, surface it
        // cleanly and send the user back to the portal root instead of
        // rendering an error state on a page they shouldn't be on.
        queryCache: new QueryCache({
          onError: (error, query) => {
            if (!(error instanceof ApiError)) return;
            if (error.status !== 403 && error.status !== 404) return;
            const firstKey = query.queryKey?.[0];
            if (firstKey !== "franchisee-portal") return;
            if (typeof window === "undefined") return;
            // Avoid bouncing back from /franchisee itself.
            if (window.location.pathname === "/franchisee") return;
            toast.error("Access denied");
            window.location.href = "/franchisee";
          },
        }),
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}