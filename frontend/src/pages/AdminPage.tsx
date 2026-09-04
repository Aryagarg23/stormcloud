import { type FormEvent, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import {
  EmptyState,
  ErrorNotice,
  formatDate,
  Loading,
  PageHeader,
  Panel,
  StatusBadge,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { api } from "../lib/api";
import type { Role } from "../lib/types";

export function AdminPage() {
  const { user } = useAuth();
  const invitations = useResource(() => api.admin.listInvitations());
  const users = useResource(() => api.admin.listUsers());
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [expires, setExpires] = useState(72);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [createdUrl, setCreatedUrl] = useState<string>();

  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.admin.invite(email, role, expires);
      setCreatedUrl(result.invite_url);
      setEmail("");
      await invitations.reload();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  if (user?.role !== "admin") {
    return <EmptyState title="Administrator access required">Only workspace administrators can manage invitations and members.</EmptyState>;
  }

  return (
    <>
      <PageHeader eyebrow="Workspace administration" title="Members & invitations" description="Stormcloud has no public registration. Every account begins with a time-limited, single-use invitation." />
      <div className="admin-grid">
        <Panel title="Invite a member">
          {Boolean(error) && <ErrorNotice error={error} />}
          {createdUrl && (
            <div className="success-notice" role="status">
              <strong>Invitation created</strong>
              <span>Email delivery is queued.</span>
              <button className="text-button" onClick={() => void navigator.clipboard.writeText(createdUrl)}>Copy invitation link</button>
            </div>
          )}
          <form className="stacked-form" onSubmit={invite}>
            <label>Email<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <div className="field-row">
              <label>Role<select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="member">Member</option><option value="admin">Admin</option></select></label>
              <label>Expires in<select value={expires} onChange={(event) => setExpires(Number(event.target.value))}><option value={24}>24 hours</option><option value={72}>3 days</option><option value={168}>7 days</option></select></label>
            </div>
            <button className="button button-primary" disabled={busy}>{busy ? "Creating..." : "Create invitation"}</button>
          </form>
        </Panel>
        <Panel title="Pending invitations">
          {invitations.loading && <Loading />}
          {Boolean(invitations.error) && <ErrorNotice error={invitations.error} onRetry={() => void invitations.reload()} />}
          {!invitations.loading && !invitations.data?.items.length && <p className="muted">No invitations.</p>}
          <div className="admin-list">
            {invitations.data?.items.map((invitation) => (
              <div className="admin-row" key={invitation.id}>
                <div><strong>{invitation.email}</strong><small>{invitation.role} - expires {formatDate(invitation.expires_at)}</small></div>
                <div><StatusBadge status={invitation.status || "pending"} />{invitation.status === "pending" && <button className="text-button danger" onClick={() => void api.admin.revokeInvitation(invitation.id).then(invitations.reload)}>Revoke</button>}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <Panel title="Workspace members">
        {users.loading && <Loading />}
        {Boolean(users.error) && <ErrorNotice error={users.error} onRetry={() => void users.reload()} />}
        <div className="admin-list">
          {users.data?.items.map((member) => (
            <div className="admin-row member-row" key={member.id}>
              <div className="identity"><span className="avatar">{member.email[0].toUpperCase()}</span><span><strong>{member.email}</strong><small>Joined {formatDate(member.created_at)}</small></span></div>
              <div className="member-actions">
                <select aria-label={"Role for " + member.email} value={member.role} disabled={member.id === user.id} onChange={(event) => void api.admin.updateUser(member.id, { role: event.target.value as Role }).then(users.reload)}>
                  <option value="member">Member</option><option value="admin">Admin</option>
                </select>
                <label className="compact-toggle"><input type="checkbox" checked={member.is_active !== false} disabled={member.id === user.id} onChange={(event) => void api.admin.updateUser(member.id, { active: event.target.checked }).then(users.reload)} /> Active</label>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}
