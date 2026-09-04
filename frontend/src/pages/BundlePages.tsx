import { Link, useParams } from "react-router-dom";
import { useEffect } from "react";
import {
  DataLabel,
  EmptyState,
  ErrorNotice,
  formatDate,
  Loading,
  PageHeader,
  Panel,
  Pipeline,
  StatusBadge,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { api } from "../lib/api";
import type { BundleItem } from "../lib/types";

export function BundlesPage() {
  const resource = useResource(() => api.bundles.list());
  const bundles = resource.data?.items ?? [];
  return (
    <>
      <PageHeader
        title="Bundles"
        actions={<Link className="button button-primary" to="/bundles/new">New bundle</Link>}
      />
      {resource.loading && <Loading label="Loading bundles" />}
      {Boolean(resource.error) && <ErrorNotice error={resource.error} onRetry={() => void resource.reload()} />}
      {!resource.loading && !resource.error && !bundles.length && (
        <EmptyState title="No bundles yet" action={<Link className="button button-primary" to="/bundles/new">Build a bundle</Link>}>
          Connect multiple sources around a thesis or a meaningful sequence.
        </EmptyState>
      )}
      <div className="bundle-grid">
        {bundles.map((bundle) => (
          <Link className="bundle-card" to={"/bundles/" + bundle.id} key={bundle.id}>
            <div className="card-topline"><DataLabel kind="human" /><StatusBadge status={bundle.status} /></div>
            <h2>{bundle.thesis || "Untitled source bundle"}</h2>
            <div className="bundle-preview" aria-hidden="true">
              {bundle.items.slice(0, 5).map((item, index) => <span key={item.id || index}>{index + 1}</span>)}
            </div>
            <div className="card-footer"><span>{bundle.items.length} signals - {bundle.ordered ? "ordered" : "unordered"}</span><time>{formatDate(bundle.created_at)}</time></div>
          </Link>
        ))}
      </div>
    </>
  );
}

export function BundlePage() {
  const { id = "" } = useParams();
  const resource = useResource(() => api.bundles.get(id), [id]);
  const bundle = resource.data;
  const bundleStatus = bundle?.status;
  const reload = resource.reload;

  useEffect(() => {
    if (!bundleStatus || bundleStatus === "ready" || bundleStatus === "failed") return;
    const timer = window.setInterval(() => void reload(), 2500);
    return () => window.clearInterval(timer);
  }, [bundleStatus, reload]);

  if (resource.loading && !bundle) return <Loading label="Loading bundle" />;
  if (resource.error && !bundle) return <ErrorNotice error={resource.error} onRetry={() => void resource.reload()} />;
  if (!bundle) return null;

  return (
    <>
      <PageHeader
        title={bundle.thesis || "Untitled source bundle"}
        actions={<StatusBadge status={bundle.status} />}
      />
      <Pipeline status={bundle.status} />
      <div className="detail-grid bundle-detail">
        <Panel title="Sources" label={<DataLabel kind="human" />}>
          <ol className={"topology " + (bundle.ordered ? "ordered" : "")}>
            {[...bundle.items].sort((a, b) => a.position - b.position).map((item, index, sorted) => (
              <li key={item.id || item.signal_id || index}>
                <BundleNode item={item} />
                {bundle.ordered && index < sorted.length - 1 && (
                  <div className="next-edge" aria-label="Next source"><span>then</span><b aria-hidden="true">↓</b></div>
                )}
              </li>
            ))}
          </ol>
        </Panel>
        <aside className="detail-aside">
          <Panel title="Source status" label={<DataLabel kind="machine" />}>
            <p className="muted">All sources must finish before the bundle is ready.</p>
            <div className="member-statuses">
              {bundle.items.map((item, index) => (
                <div key={item.id || index}><span>Item {item.position + 1}</span><StatusBadge status={item.signal?.status || "accepted"} /></div>
              ))}
            </div>
          </Panel>
          <Panel title="Summary">
            <div className="metric"><strong>{bundle.evidence_snapshots?.length ?? 0}</strong><span>Saved versions</span></div>
            <div className="metric"><strong>{bundle.embeddings?.length ?? 0}</strong><span>Search indexes</span></div>
            <div className="metric"><strong>{bundle.neighbors?.length ?? 0}</strong><span>Similar bundles</span></div>
          </Panel>
        </aside>
      </div>
    </>
  );
}

function BundleNode({ item }: { item: BundleItem }) {
  const signal = item.signal;
  const body = (
    <div className="topology-node">
      <span className="position">{item.position + 1}</span>
      <div>
        <strong>{signal?.title || signal?.description_verbatim || item.url || "Signal " + (item.position + 1)}</strong>
        {item.note && <p><DataLabel kind="human" /> {item.note}</p>}
      </div>
      {signal && <StatusBadge status={signal.status} />}
    </div>
  );
  return item.signal_id ? <Link to={"/signals/" + item.signal_id}>{body}</Link> : body;
}
