import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { listSchemas, listSchemaAccess, grantSchemaAccess, revokeSchemaAccess } from "../api/data";
import { hasToken } from "../api/client";

interface Field { id: string; name: string; dtype: string; required: boolean }
interface Schema { id: string; name: string; description: string | null; parent_id: string | null; fields: Field[] }
interface AccessGrant { id: string; subject_type: string; subject_id: string | null; role: string }

function AccessPanel({
  owner, name, schema,
}: { owner: string; name: string; schema: Schema }) {
  const [open, setOpen] = useState(false);
  const [subjectType, setSubjectType] = useState("user");
  const [subjectId, setSubjectId] = useState("");
  const [role, setRole] = useState("read");
  const qc = useQueryClient();

  const { data: grants } = useQuery<AccessGrant[]>({
    queryKey: ["schema-access", owner, name, schema.name],
    queryFn: () => listSchemaAccess(owner, name, schema.name),
    enabled: open,
  });

  const grant = useMutation({
    mutationFn: () => grantSchemaAccess(owner, name, schema.name, {
      subject_type: subjectType,
      subject_id: subjectId || undefined,
      role,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schema-access", owner, name, schema.name] });
      setSubjectId("");
    },
  });

  const revoke = useMutation({
    mutationFn: (grantId: string) => revokeSchemaAccess(owner, name, schema.name, grantId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schema-access", owner, name, schema.name] }),
  });

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1"
      >
        <span>Access permissions</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          {grants && grants.length > 0 && (
            <div className="space-y-1">
              {grants.map((g) => (
                <div key={g.id} className="flex items-center gap-2 text-xs bg-gray-50 rounded px-2 py-1">
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
            <p className="text-xs text-gray-400">No access restrictions — inherits from repo.</p>
          )}

          <div className="flex gap-2 items-center">
            <select
              value={subjectType}
              onChange={(e) => setSubjectType(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1"
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
                className="text-xs border border-gray-200 rounded px-2 py-1 w-40 font-mono"
              />
            )}
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1"
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

export default function SchemasPage() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  const isLoggedIn = hasToken();
  const { data, isLoading, error } = useQuery<Schema[]>({
    queryKey: ["schemas", owner, name],
    queryFn: () => listSchemas(owner!, name!),
    enabled: !!owner && !!name,
  });

  if (isLoading) return <p className="text-sm text-gray-400">Loading schemas…</p>;
  if (error) return <p className="text-sm text-red-500">Failed to load schemas.</p>;

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Schemas</h2>
      {!data?.length && <p className="text-sm text-gray-400">No schemas yet.</p>}
      <div className="space-y-4">
        {data?.map((schema) => (
          <div key={schema.id} className="border border-gray-200 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-gray-900">{schema.name}</span>
              {schema.parent_id && (
                <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">inherits</span>
              )}
            </div>
            {schema.description && <p className="text-sm text-gray-500 mb-2">{schema.description}</p>}
            <div className="flex flex-wrap gap-2">
              {schema.fields.map((f) => (
                <span
                  key={f.id}
                  className="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded px-2 py-0.5"
                >
                  {f.name}
                  <span className="text-blue-400 ml-1">{f.dtype}</span>
                  {f.required && <span className="text-red-400 ml-1">*</span>}
                </span>
              ))}
            </div>

            {isLoggedIn && (
              <AccessPanel owner={owner!} name={name!} schema={schema} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
