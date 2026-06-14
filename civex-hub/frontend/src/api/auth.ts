import { api, saveToken, clearToken } from "./client";

export interface TokenCreated {
  id: string;
  name: string;
  token: string;
  created_at: string;
}

export async function login(username: string, password: string): Promise<void> {
  const { data } = await api.post<TokenCreated>("/auth/tokens", {
    username,
    password,
    name: "webapp",
  });
  saveToken(data.token);
}

export async function logout(): Promise<void> {
  clearToken();
}
