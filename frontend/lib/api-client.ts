// Streamlined API client for TanStack Query
'use client';

import { getGlobalGetToken } from '@/contexts/AuthContext';

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

  // Get current auth token using the abstraction layer
  let token: string | null = null;

  // Client-side: get token from auth abstraction
  if (typeof window !== 'undefined') {
    const getToken = getGlobalGetToken();

    if (getToken) {
      try {
        token = await getToken();
      } catch (error) {
        console.error('❌ Failed to get auth token:', error);
      }
    } else {
      console.warn('⚠️ Auth not initialized yet');
    }
  }

  const config: RequestInit = {
    headers: {
      "Content-Type": "application/json",
      ...(token && {
        "Authorization": `Bearer ${token}`
      }),
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorDetails = 'Unknown error';
    try {
      const errorText = await response.text();
      errorDetails = errorText;
    } catch (e) {
      console.error('Failed to read error response:', e);
    }

    throw new ApiError(
      response.status,
      response.statusText,
      `API request failed: ${response.status} ${response.statusText} - ${errorDetails}`
    );
  }

  const responseData = await response.json();

  return responseData;
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