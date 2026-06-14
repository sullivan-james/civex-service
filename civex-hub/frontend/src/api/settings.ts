import { api } from "./client";

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  bio: string | null;
  avatar_url: string | null;
  created_at: string;
}

export interface SSHKey {
  id: string;
  title: string;
  fingerprint: string;
  created_at: string;
  last_used_at: string | null;
}

export interface APIToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export interface OrgMembership {
  org_id: string;
  org_name: string;
  org_display_name: string;
  role: string;
  joined_at: string | null;
}

export const getProfile = (): Promise<UserProfile> =>
  api.get("/api/v1/settings/profile").then((r) => r.data);

export const updateProfile = (body: Partial<Pick<UserProfile, "username" | "display_name" | "bio" | "avatar_url">>) =>
  api.patch("/api/v1/settings/profile", body).then((r) => r.data);

export const listSSHKeys = (): Promise<SSHKey[]> =>
  api.get("/api/v1/settings/ssh-keys").then((r) => r.data);

export const addSSHKey = (title: string, public_key: string): Promise<SSHKey> =>
  api.post("/api/v1/settings/ssh-keys", { title, public_key }).then((r) => r.data);

export const deleteSSHKey = (id: string) =>
  api.delete(`/api/v1/settings/ssh-keys/${id}`);

export const listTokens = (): Promise<APIToken[]> =>
  api.get("/api/v1/settings/tokens").then((r) => r.data);

export const createToken = (name: string): Promise<{ id: string; name: string; token: string; created_at: string }> =>
  api.post("/api/v1/settings/tokens", { name }).then((r) => r.data);

export const revokeToken = (id: string) =>
  api.delete(`/api/v1/settings/tokens/${id}`);

export const listMyOrgs = (): Promise<OrgMembership[]> =>
  api.get("/api/v1/settings/orgs").then((r) => r.data);
