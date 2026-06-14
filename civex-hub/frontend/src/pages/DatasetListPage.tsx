import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { listDatasets, listDatasetAccess, grantDatasetAccess, revokeDatasetAccess } from "../api/data";
import { hasToken } from "../api/client";

interface Dataset { id: string; name: string; description: string | null; record_count: number }
interface AccessGrant { id: string; subject_type: string; subject_id: string | null; role: string }

function DatasetAccessPanel({ owner, name, dataset }: { owner: string; name: string; dataset: Dataset }) {
  const [open, setOpen] = useState(false);
  const [subjectType, setSubjectType] = useState("user");
  const [subjectId, setSubjectId] = useState("");
  const [role, setRole] = useState("read");
  const qc = useQueryClient();

  const { data: grants } = useQuery<AccessGrant[]>({
    queryKey: ["dataset-access", owner, name, dataset.name],
    queryFn: () => listDatasetAccess(owner, name, dataset.name),
    enabled: open,
  });

  const grant = useMutation({
    mutationFn: () =>
      grantDatasetAccess(owner, name, dataset.name, {
        subject_type: subjectType,
        subject_id: subjectId || undefined,
        role,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dataset-access", owner, name, dataset.name] });
      setSubjectId("");
    },
  });

  const revoke = useMutation({
    mutationFn: (grantId: string) => revokeDatasetAccess(owner, name, dataset.name, grantId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dataset-access", owner, name, dataset.name] }),
  });

  const hasRestrictions = grants && grants.length > 0;

  return (
    <div className="mt-1">
      <button
        onClick={(e) => { e.preventDefault(); setOpen((o) => !o); }}
        className="text-xs text-gray-400 hover:text-gray-700 flex items-center gap-1"
      >
        {hasRestrictions
          ? <span className="text-amber-600">🔒 {grants.length} access rule(s)</span>
          : <span>Manage access</span>}
        <span className="ml-1">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 bg-gray-50 rounded-lg p-3">
          {grants && grants.length > 0 && (
            <div className="space-y-1">
              {grants.map((g) => (
                <div key={g.id} className="flex items-center gap-2 text-xs">
                  <span className="text-gray-500">{g.subject_type}</span>
                  <span className="font-mono text-gray-700">{g.subject_id?.slice(0, 8) ?? "public"}</span>
                  <span className={`px-1.5 py-0.5 rounded font-medium ${
                    g.role === "write" ? "bg-blue-100 text-blue-700" :
                    g.role === "none" ? "bg-red-100 text-red-600" :
                    "bg-gray-100 text-gray-600"
                  }`}>{g.role}</span>
                  <button
                    onClick={() => revoke.mutate(g.id)}
                    className="ml-auto text-red-400 hover:text-red-600"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          {(!grants || grants.length === 0) && (
            <p className="text-xs text-gray-400">No restrictions — inherits from repo visibility.</p>
          )}

          <div className="flex gap-2 items-center flex-wrap">
            <select
              value={subjectType}
              onChange={(e) => setSubjectType(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1 bg-white"
            >
              <option value="user">User</option>
              <option value="team">Team</option>
              <option value="org">Org</option>
              <option value="public">Public</option>
            </select>
            {subjectType !== "public" && (
              <input
                placeholder="Subject UUID"
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
                className="text-xs border border-gray-200 rounded px-2 py-1 w-40 font-mono bg-white"
              />
            )}
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1 bg-white"
            >
              <option value="read">Read</option>
              <option value="write">Write</option>
              <option value="none">None (block)</option>
            </select>
            <button
              onClick={() => grant.mutate()}
              className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700"
            >
              Grant
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DatasetListPage() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  const isLoggedIn = hasToken();
  const { data, isLoading, error } = useQuery<Dataset[]>({
    queryKey: ["datasets", owner, name],
    queryFn: () => listDatasets(owner!, name!),
    enabled: !!owner && !!name,
  });

  if (isLoading) return <p className="text-sm text-gray-400">Loading datasets…</p>;
  if (error) return <p className="text-sm text-red-500">Failed to load datasets.</p>;

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Datasets</h2>
      {!data?.length && <p className="text-sm text-gray-400">No datasets yet.</p>}
      <div className="space-y-2">
        {data?.map((ds) => (
          <div key={ds.id} className="border border-gray-200 rounded-lg px-4 py-3">
            <div className="flex items-center justify-between">
              <Link
                to={`/${owner}/${name}/datasets/${ds.name}`}
                className="font-medium text-gray-900 hover:text-blue-600"
              >
                {ds.name}
              </Link>
              <span className="text-sm text-gray-500">{ds.record_count} records</span>
            </div>
            {ds.description && <p className="text-xs text-gray-400 mt-0.5">{ds.description}</p>}
            {isLoggedIn && (
              <DatasetAccessPanel owner={owner!} name={name!} dataset={ds} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
