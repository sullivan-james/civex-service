import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getProfile, updateProfile, listSSHKeys, addSSHKey, deleteSSHKey,
  listTokens, createToken, revokeToken, listMyOrgs,
  type SSHKey, type APIToken, type OrgMembership,
} from "../api/settings";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 px-5 py-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function ProfileSection() {
  const qc = useQueryClient();
  const { data: profile } = useQuery({ queryKey: ["profile"], queryFn: getProfile });
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (profile) {
      setUsername(profile.username);
      setDisplayName(profile.display_name ?? "");
      setBio(profile.bio ?? "");
      setAvatarUrl(profile.avatar_url ?? "");
    }
  }, [profile]);

  const save = useMutation({
    mutationFn: () =>
      updateProfile({
        username: username || undefined,
        display_name: displayName || undefined,
        bio: bio || undefined,
        avatar_url: avatarUrl || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  if (!profile) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 mb-2">
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt={profile.username} className="w-16 h-16 rounded-full object-cover" />
        ) : (
          <div className="w-16 h-16 rounded-full bg-gray-200 flex items-center justify-center text-xl font-bold text-gray-500">
            {profile.username[0].toUpperCase()}
          </div>
        )}
        <div>
          <p className="font-semibold text-gray-900">{profile.display_name || profile.username}</p>
          <p className="text-xs text-gray-400">@{profile.username} · {profile.email}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs font-medium text-gray-600">Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full text-sm border border-gray-200 rounded px-3 py-1.5"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-gray-600">Display name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Your name"
            className="mt-1 w-full text-sm border border-gray-200 rounded px-3 py-1.5"
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs font-medium text-gray-600">Bio</span>
        <textarea
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          rows={2}
          placeholder="A short bio…"
          className="mt-1 w-full text-sm border border-gray-200 rounded px-3 py-1.5 resize-none"
        />
      </label>
      <label className="block">
        <span className="text-xs font-medium text-gray-600">Avatar URL</span>
        <input
          value={avatarUrl}
          onChange={(e) => setAvatarUrl(e.target.value)}
          placeholder="https://…"
          className="mt-1 w-full text-sm border border-gray-200 rounded px-3 py-1.5"
        />
      </label>

      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Save profile
        </button>
        {saved && <span className="text-sm text-green-600">Saved!</span>}
        {save.isError && <span className="text-sm text-red-500">Error saving profile.</span>}
      </div>
    </div>
  );
}

function SSHKeysSection() {
  const qc = useQueryClient();
  const { data: keys } = useQuery<SSHKey[]>({ queryKey: ["ssh-keys"], queryFn: listSSHKeys });
  const [title, setTitle] = useState("");
  const [pubKey, setPubKey] = useState("");
  const [adding, setAdding] = useState(false);

  const add = useMutation({
    mutationFn: () => addSSHKey(title, pubKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ssh-keys"] });
      setTitle("");
      setPubKey("");
      setAdding(false);
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => deleteSSHKey(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ssh-keys"] }),
  });

  return (
    <div className="space-y-3">
      {keys && keys.length > 0 ? (
        <div className="divide-y divide-gray-100">
          {keys.map((k) => (
            <div key={k.id} className="flex items-start justify-between py-3">
              <div>
                <p className="text-sm font-medium text-gray-900">{k.title}</p>
                <p className="text-xs font-mono text-gray-500 mt-0.5">{k.fingerprint}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Added {new Date(k.created_at).toLocaleDateString()}
                  {k.last_used_at && ` · Last used ${new Date(k.last_used_at).toLocaleDateString()}`}
                </p>
              </div>
              <button
                onClick={() => del.mutate(k.id)}
                className="text-sm text-red-500 hover:text-red-700 ml-4 shrink-0"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">No SSH keys added yet.</p>
      )}

      {adding ? (
        <div className="space-y-2 border border-gray-200 rounded-lg p-4">
          <p className="text-sm font-medium text-gray-700">Add new SSH key</p>
          <input
            placeholder="Title (e.g. Work laptop)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full text-sm border border-gray-200 rounded px-3 py-1.5"
          />
          <textarea
            placeholder="Begins with ssh-rsa, ssh-ed25519, etc."
            value={pubKey}
            onChange={(e) => setPubKey(e.target.value)}
            rows={4}
            className="w-full text-xs font-mono border border-gray-200 rounded px-3 py-1.5 resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={() => add.mutate()}
              disabled={add.isPending || !title || !pubKey}
              className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              Add SSH key
            </button>
            <button onClick={() => setAdding(false)} className="text-sm text-gray-500 hover:text-gray-700">
              Cancel
            </button>
          </div>
          {add.isError && <p className="text-xs text-red-500">Failed to add key. It may already be registered.</p>}
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          + New SSH key
        </button>
      )}
    </div>
  );
}

function TokensSection() {
  const qc = useQueryClient();
  const { data: tokens } = useQuery<APIToken[]>({ queryKey: ["tokens"], queryFn: listTokens });
  const [name, setName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const create = useMutation({
    mutationFn: () => createToken(name),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["tokens"] });
      setNewToken(data.token);
      setName("");
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeToken(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }),
  });

  return (
    <div className="space-y-3">
      {newToken && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-xs">
          <p className="font-medium text-green-800 mb-1">Token created — copy it now, it won't be shown again.</p>
          <code className="font-mono text-green-900 break-all select-all">{newToken}</code>
          <button onClick={() => setNewToken(null)} className="ml-3 text-green-600 hover:text-green-800">Dismiss</button>
        </div>
      )}

      {tokens && tokens.length > 0 ? (
        <div className="divide-y divide-gray-100">
          {tokens.map((t) => (
            <div key={t.id} className="flex items-start justify-between py-3">
              <div>
                <p className="text-sm font-medium text-gray-900">{t.name}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Created {new Date(t.created_at).toLocaleDateString()}
                  {t.last_used_at && ` · Last used ${new Date(t.last_used_at).toLocaleDateString()}`}
                </p>
              </div>
              <button
                onClick={() => revoke.mutate(t.id)}
                className="text-sm text-red-500 hover:text-red-700 ml-4"
              >
                Revoke
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">No tokens yet.</p>
      )}

      {adding ? (
        <div className="flex gap-2 items-center">
          <input
            placeholder="Token name (e.g. CI token)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="text-sm border border-gray-200 rounded px-3 py-1.5 flex-1"
          />
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending || !name}
            className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            Generate
          </button>
          <button onClick={() => setAdding(false)} className="text-sm text-gray-500">Cancel</button>
        </div>
      ) : (
        <button onClick={() => setAdding(true)} className="text-sm text-blue-600 hover:text-blue-800">
          + Generate new token
        </button>
      )}
    </div>
  );
}

function OrgsSection() {
  const { data: orgs } = useQuery<OrgMembership[]>({ queryKey: ["my-orgs"], queryFn: listMyOrgs });

  if (!orgs || orgs.length === 0) {
    return <p className="text-sm text-gray-400">Not a member of any organisations.</p>;
  }

  return (
    <div className="divide-y divide-gray-100">
      {orgs.map((m) => (
        <div key={m.org_id} className="flex items-center justify-between py-3">
          <div>
            <p className="text-sm font-medium text-gray-900">{m.org_display_name}</p>
            <p className="text-xs text-gray-400">@{m.org_name}</p>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${
            m.role === "owner" ? "bg-purple-100 text-purple-700" : "bg-gray-100 text-gray-600"
          }`}>{m.role}</span>
        </div>
      ))}
    </div>
  );
}

export default function UserSettingsPage() {
  const [tab, setTab] = useState<"profile" | "security" | "orgs">("profile");

  const tabClass = (t: typeof tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? "border-blue-600 text-blue-700"
        : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
    }`;

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold mb-6">Settings</h1>

      <div className="flex border-b border-gray-200 mb-6 -mx-1">
        <button className={tabClass("profile")} onClick={() => setTab("profile")}>Profile</button>
        <button className={tabClass("security")} onClick={() => setTab("security")}>Security</button>
        <button className={tabClass("orgs")} onClick={() => setTab("orgs")}>Organisations</button>
      </div>

      <div className="space-y-6">
        {tab === "profile" && (
          <Section title="Public profile">
            <ProfileSection />
          </Section>
        )}

        {tab === "security" && (
          <>
            <Section title="SSH keys">
              <SSHKeysSection />
            </Section>
            <Section title="API tokens">
              <TokensSection />
            </Section>
          </>
        )}

        {tab === "orgs" && (
          <Section title="Organisation memberships">
            <OrgsSection />
          </Section>
        )}
      </div>
    </div>
  );
}
