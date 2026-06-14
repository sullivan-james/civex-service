import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useNavigate, NavLink, Outlet } from "react-router-dom";
import { getRepo } from "../api/repos";

function CloneUrl({ owner, name }: { owner: string; name: string }) {
  const url = `${window.location.origin}/${owner}/${name}`;
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex items-center gap-2 bg-gray-100 rounded px-3 py-2 text-sm font-mono">
      <span className="flex-1 truncate">{url}</span>
      <button onClick={copy} className="text-xs text-gray-600 hover:text-gray-900 shrink-0">
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
    isActive
      ? "border-blue-600 text-blue-700"
      : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
  }`;

export default function RepoPage() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  const navigate = useNavigate();

  const { data: repo, isLoading, error } = useQuery({
    queryKey: ["repo", owner, name],
    queryFn: () => getRepo(owner!, name!),
    enabled: !!owner && !!name,
  });

  if (isLoading) return <p className="text-gray-500 text-sm">Loading…</p>;
  if (error || !repo)
    return (
      <div>
        <p className="text-red-600 text-sm mb-2">Repository not found.</p>
        <button onClick={() => navigate("/")} className="text-sm underline text-gray-600">
          Back to home
        </button>
      </div>
    );

  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <button onClick={() => navigate("/")} className="text-sm text-gray-500 hover:text-gray-800">
          civex-hub
        </button>
        <span className="text-gray-400">/</span>
        <h1 className="text-xl font-semibold">
          {repo.owner}/{repo.name}
        </h1>
        <span
          className={`text-xs px-2 py-0.5 rounded-full ml-2 ${
            repo.is_public ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"
          }`}
        >
          {repo.is_public ? "public" : "private"}
        </span>
      </div>

      {repo.description && <p className="text-gray-500 text-sm mb-2">{repo.description}</p>}

      <div className="flex border-b border-gray-200 mt-4 mb-6 -mx-1">
        <NavLink to={`/${owner}/${name}`} end className={tabClass}>Overview</NavLink>
        <NavLink to={`/${owner}/${name}/schemas`} className={tabClass}>Schemas</NavLink>
        <NavLink to={`/${owner}/${name}/datasets`} className={tabClass}>Datasets</NavLink>
        <NavLink to={`/${owner}/${name}/commits`} className={tabClass}>Commits</NavLink>
      </div>

      <Outlet context={{ repo }} />
    </div>
  );
}

export function RepoOverview({ owner, name }: { owner: string; name: string }) {
  const { data: repo } = useQuery({
    queryKey: ["repo", owner, name],
    queryFn: () => getRepo(owner!, name!),
  });
  if (!repo) return null;

  return (
    <div className="mt-2">
      <p className="text-sm font-medium text-gray-700 mb-2">Clone this repository</p>
      <CloneUrl owner={repo.owner} name={repo.name} />
      <p className="text-xs text-gray-400 mt-2">
        Run{" "}
        <code className="bg-gray-100 px-1 rounded">
          civex auth login {window.location.origin}
        </code>{" "}
        then{" "}
        <code className="bg-gray-100 px-1 rounded">
          civex clone {window.location.origin}/{repo.owner}/{repo.name}
        </code>
      </p>
      <div className="border-t border-gray-200 pt-4 mt-6">
        <p className="text-xs text-gray-400">Created {new Date(repo.created_at).toLocaleString()}</p>
      </div>
    </div>
  );
}
