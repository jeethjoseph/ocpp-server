// API client for Capacitor app with Clerk authentication
import { useAuth } from '@clerk/clerk-react';

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  statusText: string;

  constructor(
    status: number,
    statusText: string,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

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

// Factory function that accepts a token
export const createApiClient = (getToken: () => Promise<string | null>) => ({
  get: async <T>(endpoint: string) => {
    const token = await getToken();
    return apiRequest<T>(endpoint, { method: "GET" }, token);
  },

  post: async <T>(endpoint: string, data?: unknown) => {
    const token = await getToken();
    return apiRequest<T>(endpoint, {
      method: "POST",
      body: data ? JSON.stringify(data) : undefined,
    }, token);
  },

  put: async <T>(endpoint: string, data?: unknown) => {
    const token = await getToken();
    return apiRequest<T>(endpoint, {
      method: "PUT",
      body: data ? JSON.stringify(data) : undefined,
    }, token);
  },

  delete: async <T>(endpoint: string) => {
    const token = await getToken();
    return apiRequest<T>(endpoint, { method: "DELETE" }, token);
  },
});

// Hook to use the API client with authentication
export const useApi = () => {
  const { getToken } = useAuth();
  return createApiClient(getToken);
};
