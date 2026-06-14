import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getCommitAudit, listCommits } from "../api/data";

interface Commit {
  id: string;
  message: string | null;
  created_at: string | null;
  record_count: number;
  schema_count: number;
  dataset_count: number;
  pushed_by: string | null;
  pushed_at: string | null;
}

interface AuditEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  old_data: unknown;
  new_data: unknown;
  timestamp: string | null;
}

function CommitRow({ commit, owner, name }: { commit: Commit; owner: string; name: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data: entries } = useQuery<AuditEntry[]>({
    queryKey: ["commit-audit", owner, name, commit.id],
    queryFn: () => getCommitAudit(owner, name, commit.id),
    enabled: expanded,
  });

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center gap-3"
        onClick={() => setExpanded((e) => !e)}
      >
        <span className="font-mono text-xs text-gray-400 shrink-0">{commit.id.slice(0, 8)}</span>
        <span className="flex-1 font-medium text-gray-800">{commit.message || <span className="italic text-gray-400">no message</span>}</span>
        <span className="text-xs text-gray-400 shrink-0">
          {commit.pushed_by ? `pushed by ${commit.pushed_by}` : "local"}
        </span>
        <span className="text-xs text-gray-400 shrink-0">
          {commit.created_at ? new Date(commit.created_at).toLocaleDateString() : ""}
        </span>
        <div className="flex gap-2 text-xs text-gray-500 shrink-0">
          {commit.record_count > 0 && <span>{commit.record_count}r</span>}
          {commit.schema_count > 0 && <span>{commit.schema_count}s</span>}
          {commit.dataset_count > 0 && <span>{commit.dataset_count}d</span>}
        </div>
        <span className="text-gray-400 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 space-y-1">
          {!entries && <p className="text-xs text-gray-400">Loading…</p>}
          {entries?.length === 0 && <p className="text-xs text-gray-400">No audit entries.</p>}
          {entries?.map((e) => (
            <div key={e.id} className="flex items-center gap-2 text-xs">
              <span className={`px-1.5 py-0.5 rounded font-medium ${
                e.action === "create" ? "bg-green-100 text-green-700"
                : e.action === "delete" ? "bg-red-100 text-red-700"
                : "bg-yellow-100 text-yellow-700"
              }`}>{e.action}</span>
              <span className="text-gray-500">{e.entity_type}</span>
              {e.entity_type === "record" ? (
                <Link
                  to={`/${owner}/${name}/records/${e.entity_id}`}
                  className="font-mono text-blue-500 hover:underline"
                >
                  {e.entity_id.slice(0, 8)}
                </Link>
              ) : (
                <span className="font-mono text-gray-400">{e.entity_id.slice(0, 8)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CommitHistoryPage() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  const { data, isLoading, error } = useQuery<Commit[]>({
    queryKey: ["commits", owner, name],
    queryFn: () => listCommits(owner!, name!),
    enabled: !!owner && !!name,
  });

  if (isLoading) return <p className="text-sm text-gray-400">Loading commits…</p>;
  if (error) return <p className="text-sm text-red-500">Failed to load commit history.</p>;

  return (
    <div>
      <h2 className="text-lg font-semibold mb-4">Commit history</h2>
      {!data?.length && <p className="text-sm text-gray-400">No commits yet.</p>}
      <div className="space-y-2">
        {data?.map((c) => (
          <CommitRow key={c.id} commit={c} owner={owner!} name={name!} />
        ))}
      </div>
    </div>
  );
}
