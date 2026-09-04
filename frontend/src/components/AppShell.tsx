import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Loading } from "./ui";

const nav = [
  { to: "/", label: "Signals", glyph: "[]", end: true },
  { to: "/submit", label: "New signal", glyph: "+" },
  { to: "/bundles", label: "Bundles", glyph: "::" },
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
          <span className="brand-mark" aria-hidden="true">S</span>
          <span>
            <strong>Stormcloud</strong>
            <small>Evidence workspace</small>
          </span>
        </NavLink>
        <nav aria-label="Primary navigation">
          {nav.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <span aria-hidden="true">{item.glyph}</span>{item.label}
            </NavLink>
          ))}
          {user?.role === "admin" && (
            <NavLink to="/admin">
              <span aria-hidden="true">@</span>Administration
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="identity">
            <span className="avatar">{user?.email.slice(0, 1).toUpperCase()}</span>
            <span><strong>{user?.email}</strong><small>{user?.role}</small></span>
          </div>
          <button className="text-button" onClick={() => void logout()}>Sign out</button>
        </div>
      </aside>
      <main className="workspace"><Outlet /></main>
    </div>
  );
}
