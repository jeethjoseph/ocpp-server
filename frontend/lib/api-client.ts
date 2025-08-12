// Streamlined API client for TanStack Query
'use client';

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
  
  // Get current auth token from Clerk
  let token: string | null = null;
  
  // Client-side: get token from window.Clerk
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (typeof window !== 'undefined' && (window as any).Clerk) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const clerk = (window as any).Clerk;
    
    
    if (clerk.session) {
      try {
        token = await clerk.session.getToken();
        
      } catch (error) {
        console.error('❌ Failed to get Clerk token:', error);
      }
    } else {
      console.warn('⚠️ No Clerk session found');
    }
  } else {
    console.warn('⚠️ Clerk not available on window object');
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