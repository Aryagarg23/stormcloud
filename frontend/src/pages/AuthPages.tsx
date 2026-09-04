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
      <section className="auth-story">
        <span className="brand-mark large" aria-hidden="true">S</span>
        <p className="eyebrow">Private research infrastructure</p>
        <h1>Trace ideas back to their evidence.</h1>
        <p>Stormcloud keeps what you wrote, what the source said, and what machines inferred as distinct, versioned layers.</p>
        <div className="trust-list">
          <span>Verbatim researcher input</span>
          <span>Immutable source versions</span>
          <span>Reproducible machine analysis</span>
        </div>
      </section>
      <section className="auth-card">
        <div>
          <p className="eyebrow">Welcome back</p>
          <h2>Sign in</h2>
          <p className="muted">Access is limited to invited members.</p>
        </div>
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
        <div>
          <span className="brand-mark" aria-hidden="true">S</span>
          <p className="eyebrow">Invitation</p>
          <h1>Join Stormcloud</h1>
          <p className="muted">Create a password to activate your workspace account.</p>
        </div>
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
