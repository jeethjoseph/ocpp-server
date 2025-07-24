// Streamlined API client for TanStack Query
import { supabase } from '@/lib/supabase';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  // Get current session token
  const { data: { session } } = await supabase.auth.getSession();
  
  const config: RequestInit = {
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token && {
        "Authorization": `Bearer ${session.access_token}`
      }),
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    // If token expired, try to refresh
    if (response.status === 401 && session) {
      const { data: { session: newSession }, error } = await supabase.auth.getSession();
      if (newSession && !error) {
        // Retry with new token
        const retryConfig: RequestInit = {
          ...config,
          headers: {
            ...config.headers,
            "Authorization": `Bearer ${newSession.access_token}`
          }
        };
        const retryResponse = await fetch(url, retryConfig);
        if (retryResponse.ok) {
          return retryResponse.json();
        }
      }
    }
    
    throw new ApiError(
      response.status,
      response.statusText,
      `API request failed: ${response.status} ${response.statusText}`
    );
  }

  return response.json();
}

export const api = {
  get: <T>(endpoint: string) => apiRequest<T>(endpoint, { method: "GET" }),
  
  post: <T>(endpoint: string, data?: unknown) =>
    apiRequest<T>(endpoint, {
      method: "POST",
      body: data ? JSON.stringify(data) : undefined,
    }),
    
  put: <T>(endpoint: string, data?: unknown) =>
    apiRequest<T>(endpoint, {
      method: "PUT",
      body: data ? JSON.stringify(data) : undefined,
    }),
    
  delete: <T>(endpoint: string) =>
    apiRequest<T>(endpoint, { method: "DELETE" }),
};