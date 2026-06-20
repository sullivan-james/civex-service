import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getRecord, getAuditLog, getRecordChildren, updateRecord, listSchemas } from "../api/data";
import type { CivexRecord } from "../api/data";
import { FieldValue } from "../components/FieldValue";

interface AuditEntry {
  id: string;
  action: string;
  commit_id: string | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  timestamp: string | null;
}

interface Schema {
  id: string;
  name: string;
  fields: { id: string; name: string; dtype: string; required: boolean }[];
}

export default function RecordDetailPage() {
  const { owner, name, recordId } = useParams<{ owner: string; name: string; recordId: string }>();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [editValues, setEditValues] = useState<Record<string, string>>({});

  const { data: record, isLoading } = useQuery<CivexRecord>({
    queryKey: ["record", owner, name, recordId],
    queryFn: () => getRecord(owner!, name!, recordId!),
    enabled: !!recordId,
  });

  const { data: audit } = useQuery<AuditEntry[]>({
    queryKey: ["record-audit", owner, name, recordId],
    queryFn: () => getAuditLog(owner!, name!, { entity_type: "record", entity_id: recordId, limit: 20 }),
    enabled: !!recordId,
  });

  const { data: children } = useQuery<CivexRecord[]>({
    queryKey: ["record-children", owner, name, recordId],
    queryFn: () => getRecordChildren(owner!, name!, recordId!),
    enabled: !!recordId,
  });

  const { data: schemas } = useQuery<Schema[]>({
    queryKey: ["schemas", owner, name],
    queryFn: () => listSchemas(owner!, name!),
    enabled: !!owner && !!name,
  });

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => updateRecord(owner!, name!, recordId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["record", owner, name, recordId] });
      setIsEditing(false);
    },
  });

  if (isLoading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (!record) return <p className="text-sm text-red-500">Record not found.</p>;

  const schema = schemas?.find(s => s.name === record.schema);
  const heading = record.natural_name ?? record.id.slice(0, 8) + "…";

  function startEditing() {
    const initial: Record<string, string> = {};
    for (const [k, v] of Object.entries(record!.data)) {
      if (v !== null && v !== undefined && typeof v !== 'object') {
        initial[k] = String(v);
      }
    }
    setEditValues(initial);
    setIsEditing(true);
  }

  function handleSave() {
    const data: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(editValues)) {
      if (v !== '') data[k] = v;
    }
    updateMutation.mutate(data);
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-1 text-sm text-gray-400">
        <Link to={`/${owner}/${name}/datasets`} className="hover:text-gray-600">Datasets</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">{heading}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold">{heading}</h2>
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-mono">{record.schema}</span>
          </div>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{record.id}</p>
        </div>
        {!isEditing && (
          <button
            onClick={startEditing}
            className="text-sm px-3 py-1.5 border border-gray-200 rounded hover:bg-gray-50 text-gray-700"
          >
            Edit
          </button>
        )}
      </div>

      {/* Parent record link */}
      {record.parent_record_id && (
        <div className="flex items-center gap-2 text-sm bg-gray-50 border border-gray-200 rounded-lg px-4 py-2">
          <span className="text-gray-500">Parent record:</span>
          <Link
            to={`/${owner}/${name}/records/${record.parent_record_id}`}
            className="font-mono text-xs text-blue-600 hover:underline"
          >
            {record.parent_record_id.slice(0, 8)}…
          </Link>
        </div>
      )}

      {/* Record fields */}
      {isEditing ? (
        <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Editing fields</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {(schema?.fields ?? Object.keys(record.data).map(n => ({ name: n, dtype: 'string', id: n, required: false }))).map(f => {
              const v = record.data[f.name];
              if (typeof v === 'object' && v !== null) return null; // skip file fields in edit mode
              return (
                <div key={f.name} className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-gray-600 font-mono">{f.name}</label>
                  <input
                    className="text-sm border border-gray-200 rounded px-2 py-1 bg-white"
                    value={editValues[f.name] ?? ''}
                    onChange={e => setEditValues(p => ({ ...p, [f.name]: e.target.value }))}
                    placeholder={typeof v === 'string' || typeof v === 'number' ? String(v) : ''}
                  />
                </div>
              );
            })}
          </div>
          {updateMutation.error && (
            <p className="text-xs text-red-500">{String(updateMutation.error)}</p>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="text-sm px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save'}
            </button>
            <button onClick={() => setIsEditing(false)} className="text-sm px-3 py-1.5 border border-gray-200 rounded hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-gray-100">
              {(schema?.fields ?? Object.keys(record.data).map(n => ({ name: n }))).map(f => (
                <tr key={f.name}>
                  <td className="px-4 py-2.5 font-medium text-gray-500 bg-gray-50 w-48 font-mono text-xs">{f.name}</td>
                  <td className="px-4 py-2.5 text-gray-900 text-sm">
                    <FieldValue value={record.data[f.name]} owner={owner!} repo={name!} />
                  </td>
                </tr>
              ))}
              {Object.keys(record.data).length === 0 && (
                <tr>
                  <td colSpan={2} className="px-4 py-3 text-gray-400 italic text-sm">No field values.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Children */}
      {children && children.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Child records ({children.length})
          </h3>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 w-40">Name / ID</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500">Schema</th>
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500">Data preview</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {children.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2">
                      <Link
                        to={`/${owner}/${name}/records/${c.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {c.natural_name ?? <span className="font-mono text-xs">{c.id.slice(0, 8)}…</span>}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{c.schema}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs font-mono truncate max-w-xs">
                      {Object.entries(c.data)
                        .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
                        .slice(0, 3)
                        .map(([k, v]) => `${k}: ${String(v)}`)
                        .join("  ·  ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Audit history */}
      {audit && audit.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Change history</h3>
          <div className="space-y-2">
            {audit.map((e) => (
              <div key={e.id} className="border border-gray-100 rounded-lg p-3 text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`px-1.5 py-0.5 rounded font-medium ${
                      e.action === "create"
                        ? "bg-green-100 text-green-700"
                        : e.action === "delete"
                        ? "bg-red-100 text-red-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {e.action}
                  </span>
                  <span className="text-gray-400">
                    {e.timestamp ? new Date(e.timestamp).toLocaleString() : ""}
                  </span>
                  {e.commit_id && (
                    <span className="text-gray-400 font-mono">commit {e.commit_id.slice(0, 8)}</span>
                  )}
                </div>
                {e.action === "update" && e.old_data && e.new_data && (
                  <div className="mt-1 space-y-1">
                    {Object.keys({ ...e.old_data, ...e.new_data }).map((k) => {
                      const oldVal = e.old_data?.[k];
                      const newVal = e.new_data?.[k];
                      if (JSON.stringify(oldVal) === JSON.stringify(newVal)) return null;
                      return (
                        <div key={k} className="flex gap-2">
                          <span className="text-gray-500 w-24 shrink-0">{k}</span>
                          <span className="line-through text-red-400">{JSON.stringify(oldVal)}</span>
                          <span className="text-gray-300">→</span>
                          <span className="text-green-600">{JSON.stringify(newVal)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
