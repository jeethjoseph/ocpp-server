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

/**
 * The server's own `detail` message from a FastAPI error, when there is one.
 *
 * Endpoints increasingly say something the UI cannot infer from a status code —
 * "the session is still running" after a charger refuses a stop, for instance.
 * Hard-coded per-status toast copy would flatly contradict that. Returns null
 * when there is no usable detail so callers keep their own fallback wording.
 */
export function serverDetail(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.message.match(/\{[\s\S]*\}\s*$/);
  if (!body) return null;
  try {
    const parsed = JSON.parse(body[0]);
    return typeof parsed?.detail === "string" && parsed.detail.trim()
      ? parsed.detail
      : null;
  } catch {
    return null;
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  // ⭐ New Relic Browser agent automatically instruments fetch() requests
  // It injects distributed tracing headers (traceparent, newrelic) to connect
  // frontend requests to backend traces. No manual header injection needed!
  // The browser agent detects fetch() calls and adds headers automatically.

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