import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorNotice } from "../components/ui";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await login(email, password);
      const target = (location.state as { from?: string } | null)?.from || "/";
      navigate(target, { replace: true });
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-card">
        <header className="auth-header">
          <strong>stormcloud</strong>
          <span>internal</span>
        </header>
        <h1>Log in</h1>
        {Boolean(error) && <ErrorNotice error={error} />}
        <form onSubmit={submit}>
          <label>Email<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" minLength={10} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button className="button button-primary button-wide" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</button>
        </form>
      </section>
    </main>
  );
}

export function AcceptInvitePage() {
  const { user, acceptInvite } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const inviteToken = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(new Error("Passwords do not match."));
      return;
    }
    if (!inviteToken) {
      setError(new Error("This invitation link is missing its token."));
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await acceptInvite(inviteToken, password);
      navigate("/", { replace: true });
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-layout single">
      <section className="auth-card">
        <header className="auth-header"><strong>stormcloud</strong><span>invitation</span></header>
        <h1>Set password</h1>
        {Boolean(error) && <ErrorNotice error={error} />}
        <form onSubmit={submit}>
          <label>Password<input type="password" autoComplete="new-password" minLength={10} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <label>Confirm password<input type="password" autoComplete="new-password" minLength={10} required value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
          <button className="button button-primary button-wide" disabled={busy || !inviteToken}>{busy ? "Activating..." : "Activate account"}</button>
        </form>
      </section>
    </main>
  );
}
