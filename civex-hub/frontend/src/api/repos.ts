import { api } from "./client";

export interface Repo {
  id: string;
  owner: string;
  name: string;
  description: string | null;
  is_public: boolean;
  created_at: string;
}

export interface CreateRepoPayload {
  name: string;
  description?: string;
  is_public?: boolean;
}

export async function listRepos(): Promise<Repo[]> {
  const { data } = await api.get<Repo[]>("/api/v1/repos");
  return data;
}

export async function getRepo(owner: string, name: string): Promise<Repo> {
  const { data } = await api.get<Repo>(`/api/v1/repos/${owner}/${name}`);
  return data;
}

export async function createRepo(payload: CreateRepoPayload): Promise<Repo> {
  const { data } = await api.post<Repo>("/api/v1/repos", payload);
  return data;
}

export async function deleteRepo(owner: string, name: string): Promise<void> {
  await api.delete(`/api/v1/repos/${owner}/${name}`);
}
