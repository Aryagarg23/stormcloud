import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Loading } from "./ui";

const nav = [
  { to: "/", label: "Signals", end: true },
  { to: "/grading", label: "Grading" },
  { to: "/bundles", label: "Bundles" },
  { to: "/submit", label: "New" },
];

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <main className="centered"><Loading label="Opening workspace" /></main>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="Stormcloud home">
          <strong>stormcloud</strong>
        </NavLink>
        <nav aria-label="Primary navigation">
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
          {user?.role === "admin" && (
            <NavLink to="/admin">Admin</NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          <span className="identity">{user?.email}</span>
          <button className="text-button" onClick={() => void logout()}>Log out</button>
        </div>
      </aside>
      <main className="workspace"><Outlet /></main>
    </div>
  );
}
