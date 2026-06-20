import { api } from "./client";

export interface SshKey {
  id: string
  title: string
  fingerprint: string
  created_at: string
  last_used_at: string | null
}

export const listSshKeys = (): Promise<SshKey[]> =>
  api.get("/api/v1/settings/ssh-keys").then(r => r.data);

export const addSshKey = (title: string, public_key: string): Promise<SshKey> =>
  api.post("/api/v1/settings/ssh-keys", { title, public_key }).then(r => r.data);

export const deleteSshKey = (id: string): Promise<void> =>
  api.delete(`/api/v1/settings/ssh-keys/${id}`);
