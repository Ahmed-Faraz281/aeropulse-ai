import axios from 'axios';

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  database: {
    status: string;
    database: string;
    ok: boolean;
    error?: string;
  };
}

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 8000,
});

// Attach Authorization Bearer token to all outgoing requests if present
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('aeropulse_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Intercept 401 responses to automatically invalidate expired session
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear token and broadcast session expired event
      localStorage.removeItem('aeropulse_token');
      localStorage.removeItem('aeropulse_user');
      window.dispatchEvent(new Event('auth-session-expired'));
    }
    return Promise.reject(error);
  }
);

export const checkHealth = async (): Promise<HealthResponse> => {
  const response = await apiClient.get<HealthResponse>('/health');
  return response.data;
};
