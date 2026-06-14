import { Outlet, Link, useNavigate } from "react-router-dom";
import { clearToken, hasToken } from "../api/client";

export default function Layout() {
  const navigate = useNavigate();
  const loggedIn = hasToken();

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-gray-900 text-white px-6 py-3 flex items-center justify-between">
        <Link to="/" className="text-lg font-semibold tracking-tight hover:text-gray-300">
          civex-hub
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          {loggedIn ? (
            <>
              <Link to="/repos/new" className="hover:text-gray-300">New repo</Link>
              <Link to="/settings" className="hover:text-gray-300">Settings</Link>
              <button onClick={handleLogout} className="hover:text-gray-300">Sign out</button>
            </>
          ) : (
            <Link to="/login" className="hover:text-gray-300">Sign in</Link>
          )}
        </nav>
      </header>
      <main className="max-w-5xl mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
