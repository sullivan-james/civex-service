import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getRecord, getAuditLog, getRecordChildren } from "../api/data";

interface RecordData {
  id: string;
  schema: string;
  dataset_id: string;
  parent_record_id: string | null;
  data: Record<string, unknown>;
}

interface AuditEntry {
  id: string;
  action: string;
  commit_id: string | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  timestamp: string | null;
}

export default function RecordDetailPage() {
  const { owner, name, recordId } = useParams<{ owner: string; name: string; recordId: string }>();

  const { data: record, isLoading } = useQuery<RecordData>({
    queryKey: ["record", owner, name, recordId],
    queryFn: () => getRecord(owner!, name!, recordId!),
    enabled: !!recordId,
  });

  const { data: audit } = useQuery<AuditEntry[]>({
    queryKey: ["record-audit", owner, name, recordId],
    queryFn: () => getAuditLog(owner!, name!, { entity_type: "record", entity_id: recordId, limit: 20 }),
    enabled: !!recordId,
  });

  const { data: children } = useQuery<RecordData[]>({
    queryKey: ["record-children", owner, name, recordId],
    queryFn: () => getRecordChildren(owner!, name!, recordId!),
    enabled: !!recordId,
  });

  if (isLoading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (!record) return <p className="text-sm text-red-500">Record not found.</p>;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Link to={`/${owner}/${name}/datasets`} className="text-sm text-gray-400 hover:text-gray-600">
            Datasets
          </Link>
          <span className="text-gray-300">/</span>
          <span className="text-sm text-gray-500 font-mono">{recordId?.slice(0, 8)}…</span>
        </div>
        <h2 className="text-lg font-semibold">Record detail</h2>
        <p className="text-xs text-gray-400 mt-1">
          Schema: <span className="font-medium">{record.schema}</span>
        </p>
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

      {/* Record data table */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-gray-100">
            {Object.entries(record.data).map(([k, v]) => (
              <tr key={k}>
                <td className="px-4 py-2 font-medium text-gray-600 bg-gray-50 w-48">{k}</td>
                <td className="px-4 py-2 text-gray-900 font-mono text-xs">{JSON.stringify(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
                  <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 w-24">ID</th>
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
                        className="font-mono text-xs text-blue-600 hover:underline"
                      >
                        {c.id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{c.schema}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs font-mono truncate max-w-xs">
                      {Object.entries(c.data)
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
