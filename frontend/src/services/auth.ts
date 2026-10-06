import { apiClient } from './api';
import type { LoginPayload, TokenResponse, User } from '../types/auth';

const TOKEN_KEY = 'aeropulse_token';
const USER_KEY = 'aeropulse_user';

export const getStoredToken = (): string | null => {
  return localStorage.getItem(TOKEN_KEY);
};

export const setStoredToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token);
};

export const getStoredUser = (): User | null => {
  const data = localStorage.getItem(USER_KEY);
  if (!data) return null;
  try {
    return JSON.parse(data) as User;
  } catch {
    return null;
  }
};

export const setStoredUser = (user: User): void => {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
};

export const clearStoredAuth = (): void => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
};

export const login = async (payload: LoginPayload): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/login', payload);
  setStoredToken(response.data.access_token);
  setStoredUser(response.data.user);
  return response.data;
};

export const getMe = async (): Promise<User> => {
  const response = await apiClient.get<User>('/auth/me');
  setStoredUser(response.data);
  return response.data;
};

export const logout = async (): Promise<void> => {
  try {
    await apiClient.post('/auth/logout');
  } catch {
    // Ignore network failure on logout; local cleanup is primary
  } finally {
    clearStoredAuth();
  }
};
