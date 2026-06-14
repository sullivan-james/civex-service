import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { listRecords } from "../api/data";
import { listSchemas } from "../api/data";

interface CivexRecord {
  id: string;
  schema: string;
  dataset_id: string;
  parent_record_id: string | null;
  data: Record<string, unknown>;
  updated_at: string | null;
}

interface Schema { id: string; name: string }

export default function RecordListPage() {
  const { owner, name, dataset } = useParams<{ owner: string; name: string; dataset: string }>();
  const [schemaFilter, setSchemaFilter] = useState("");
  const [search, setSearch] = useState("");

  const { data: schemas } = useQuery<Schema[]>({
    queryKey: ["schemas", owner, name],
    queryFn: () => listSchemas(owner!, name!),
    enabled: !!owner && !!name,
  });

  const { data, isLoading, error } = useQuery<CivexRecord[]>({
    queryKey: ["records", owner, name, dataset, schemaFilter],
    queryFn: () =>
      listRecords(owner!, name!, dataset!, {
        schema: schemaFilter || undefined,
        limit: 100,
      }),
    enabled: !!owner && !!name && !!dataset,
  });

  const filtered = search
    ? data?.filter((r) =>
        r.id.toLowerCase().includes(search.toLowerCase()) ||
        r.schema.toLowerCase().includes(search.toLowerCase()) ||
        JSON.stringify(r.data).toLowerCase().includes(search.toLowerCase())
      )
    : data;

  if (isLoading) return <p className="text-sm text-gray-400">Loading records…</p>;
  if (error) return <p className="text-sm text-red-500">Failed to load records.</p>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <Link to={`/${owner}/${name}/datasets`} className="text-sm text-gray-400 hover:text-gray-600">
          Datasets
        </Link>
        <span className="text-gray-300">/</span>
        <h2 className="text-lg font-semibold">{dataset}</h2>
      </div>

      <div className="flex gap-3 mb-4">
        <select
          value={schemaFilter}
          onChange={(e) => setSchemaFilter(e.target.value)}
          className="text-sm border border-gray-200 rounded px-2 py-1.5 bg-white text-gray-700"
        >
          <option value="">All schemas</option>
          {schemas?.map((s) => (
            <option key={s.id} value={s.name}>{s.name}</option>
          ))}
        </select>

        <input
          type="search"
          placeholder="Search records…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-sm border border-gray-200 rounded px-3 py-1.5 flex-1"
        />
      </div>

      {!filtered?.length && <p className="text-sm text-gray-400">No records found.</p>}

      {filtered && filtered.length > 0 && (
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 w-24">ID</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-gray-500">Schema</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-gray-500">Data preview</th>
                <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 w-28">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <Link
                      to={`/${owner}/${name}/records/${r.id}`}
                      className="font-mono text-xs text-blue-600 hover:underline"
                    >
                      {r.id.slice(0, 8)}…
                    </Link>
                    {r.parent_record_id && (
                      <span className="ml-1 text-xs text-gray-400 italic">child</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-600 text-xs">{r.schema}</td>
                  <td className="px-3 py-2 text-gray-500 text-xs font-mono max-w-sm truncate">
                    {Object.entries(r.data)
                      .slice(0, 3)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join("  ·  ")}
                  </td>
                  <td className="px-3 py-2 text-gray-400 text-xs">
                    {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
