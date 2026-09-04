import { Link } from "react-router-dom";
import { useResource } from "../hooks/useResource";
import { api } from "../lib/api";
import type { SignalSummary } from "../lib/types";
import {
  EmptyState,
  ErrorNotice,
  formatDate,
  Loading,
  PageHeader,
  StatusBadge,
} from "../components/ui";

export function HomePage() {
  const { data, loading, error, reload } = useResource(() => api.signals.list("?archived=false"));

  return (
    <>
      <PageHeader
        eyebrow="Research ledger"
        title="Signals"
        description="Each signal preserves your original observation while its source and machine-derived evidence evolve independently."
        actions={<Link className="button button-primary" to="/submit">New signal</Link>}
      />
      <div className="toolbar">
        <span className="muted">{data?.total ?? data?.items.length ?? 0} signals</span>
        <button className="text-button" onClick={() => void reload()}>Refresh</button>
      </div>
      {loading && <Loading label="Loading signals" />}
      {Boolean(error) && <ErrorNotice error={error} onRetry={() => void reload()} />}
      {!loading && !error && !data?.items.length && (
        <EmptyState title="No signals yet" action={<Link to="/submit" className="button button-primary">Capture the first signal</Link>}>
          Submit a source and your verbatim description. Stormcloud will build the evidence record asynchronously.
        </EmptyState>
      )}
      {!!data?.items.length && (
        <div className="signal-grid">
          {data.items.map((signal) => <SignalCard key={signal.id} signal={signal} />)}
        </div>
      )}
    </>
  );
}

function SignalCard({ signal }: { signal: SignalSummary }) {
  const host = (() => {
    try { return new URL(signal.canonical_url || signal.url).hostname; } catch { return signal.url; }
  })();
  return (
    <Link className="signal-card" to={"/signals/" + signal.id}>
      <div className="card-topline">
        <span className="source-host">{host}</span>
        <StatusBadge status={signal.status} />
      </div>
      <h2>{signal.title || signal.description_verbatim.slice(0, 90)}</h2>
      <p>{signal.description_verbatim}</p>
      <div className="card-footer">
        <span>Human input</span>
        <time>{formatDate(signal.created_at)}</time>
      </div>
    </Link>
  );
}
