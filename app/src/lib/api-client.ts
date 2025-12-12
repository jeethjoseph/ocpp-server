// API client for Capacitor app with Clerk authentication
import { useAuth } from '@clerk/clerk-react';
import { Capacitor, CapacitorHttp } from '@capacitor/core';

// Determine API URL based on platform
// On native platforms, use production URL or custom configured URL
// On web/dev, use localhost or configured URL
const getApiUrl = () => {
  const isNative = Capacitor.isNativePlatform();
  const configuredUrl = import.meta.env.VITE_API_URL;

  if (isNative) {
    // On native platform, must use production URL (localhost won't work)
    return configuredUrl || "https://lyncpower.com";
  } else {
    // On web platform, can use localhost or production
    return configuredUrl || "http://localhost:8000";
  }
};

const API_BASE_URL = getApiUrl();

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
  const isNative = Capacitor.isNativePlatform();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token && {
      "Authorization": `Bearer ${token}`
    }),
    ...(options.headers as Record<string, string> || {}),
  };

  // Use CapacitorHttp on native platforms to bypass CORS
  if (isNative) {
    try {
      const response = await CapacitorHttp.request({
        method: (options.method as string) || 'GET',
        url,
        headers,
        data: options.body ? JSON.parse(options.body as string) : undefined,
      });

      if (response.status >= 400) {
        const errorDetails = typeof response.data === 'string'
          ? response.data
          : JSON.stringify(response.data);

        throw new ApiError(
          response.status,
          `HTTP ${response.status}`,
          `API request failed: ${response.status} - ${errorDetails}`
        );
      }

      return response.data as T;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(
        500,
        'Network Error',
        `API request failed: ${error instanceof Error ? error.message : 'Unknown error'}`
      );
    }
  }

  // Use standard fetch on web platforms
  const config: RequestInit = {
    headers,
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
