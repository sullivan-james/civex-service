import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listRepos, type Repo } from "../api/repos";

function RepoCard({ repo }: { repo: Repo }) {
  return (
    <Link
      to={`/${repo.owner}/${repo.name}`}
      className="block border border-gray-200 rounded-lg p-4 hover:border-gray-400 transition-colors bg-white"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-gray-900">
          {repo.owner}/{repo.name}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${repo.is_public ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
          {repo.is_public ? "public" : "private"}
        </span>
      </div>
      {repo.description && (
        <p className="text-sm text-gray-500 mt-1">{repo.description}</p>
      )}
      <p className="text-xs text-gray-400 mt-2">
        Created {new Date(repo.created_at).toLocaleDateString()}
      </p>
    </Link>
  );
}

export default function HomePage() {
  const { data: repos, isLoading, error } = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">Repositories</h1>
        <Link
          to="/repos/new"
          className="bg-gray-900 text-white rounded px-4 py-2 text-sm font-medium hover:bg-gray-700"
        >
          New repository
        </Link>
      </div>

      {isLoading && <p className="text-gray-500 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">Failed to load repositories.</p>}

      {repos && repos.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg mb-2">No repositories yet.</p>
          <Link to="/repos/new" className="text-sm underline">Create your first repository</Link>
        </div>
      )}

      {repos && repos.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {repos.map((r) => <RepoCard key={r.id} repo={r} />)}
        </div>
      )}
    </div>
  );
}
