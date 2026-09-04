import {
  type MouseEvent as ReactMouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useParams } from "react-router-dom";
import {
  DataLabel,
  ErrorNotice,
  formatDate,
  Loading,
  PageHeader,
  Panel,
  Pipeline,
  StatusBadge,
} from "../components/ui";
import { api } from "../lib/api";
import { useResource } from "../hooks/useResource";
import type { Highlight, SignalDetail } from "../lib/types";

type Tab = "overview" | "source" | "provenance";

export function SignalPage() {
  const { id = "" } = useParams();
  const resource = useResource(() => api.signals.get(id), [id]);
  const { data: signal, error, loading, reload } = resource;
  const [tab, setTab] = useState<Tab>("overview");
  const [mutationError, setMutationError] = useState<unknown>();
  const [retrying, setRetrying] = useState(false);

  const signalStatus = signal?.status;
  useEffect(() => {
    if (!signalStatus || signalStatus === "ready" || signalStatus === "failed") return;
    const timer = window.setInterval(() => void reload(), 2400);
    return () => window.clearInterval(timer);
  }, [signalStatus, reload]);

  async function retry() {
    setRetrying(true);
    setMutationError(undefined);
    try {
      await api.signals.retry(id);
      await reload();
    } catch (reason) {
      setMutationError(reason);
    } finally {
      setRetrying(false);
    }
  }

  if (loading && !signal) return <Loading label="Loading signal" />;
  if (error && !signal) return <ErrorNotice error={error} onRetry={() => void reload()} />;
  if (!signal) return null;

  return (
    <>
      <PageHeader
        eyebrow="Signal"
        title={signal.title || signal.description_verbatim.slice(0, 110)}
        description={signal.canonical_url || signal.url}
        actions={
          <div className="button-row">
            <StatusBadge status={signal.status} />
            <a className="button" href={signal.canonical_url || signal.url} target="_blank" rel="noreferrer">Open original</a>
          </div>
        }
      />
      <Pipeline status={signal.status} />
      {Boolean(mutationError) && <ErrorNotice error={mutationError} />}
      {signal.failure && (
        <div className="error-notice" role="alert">
          <strong>{signal.failure.stage ? "Failed during " + signal.failure.stage : "Processing failed"}</strong>
          <span>{signal.failure.detail}</span>
          {signal.failure.retryable !== false && <button className="button button-small" disabled={retrying} onClick={() => void retry()}>{retrying ? "Retrying..." : "Retry stage"}</button>}
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Signal detail">
        {(["overview", "source", "provenance"] as Tab[]).map((value) => (
          <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
            {value === "source" ? "Source & highlights" : value[0].toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview signal={signal} />}
      {tab === "source" && <SourceView signal={signal} reload={reload} />}
      {tab === "provenance" && <Provenance signal={signal} />}
    </>
  );
}

function Overview({ signal }: { signal: SignalDetail }) {
  return (
    <div className="detail-grid">
      <div className="detail-main">
        <Panel title="Researcher observation" label={<DataLabel kind="human" />}>
          <blockquote className="verbatim">{signal.description_verbatim}</blockquote>
          <p className="metadata">Submitted {formatDate(signal.created_at)} - preserved verbatim</p>
        </Panel>
        <Panel title="Constrained extraction" label={<DataLabel kind="machine" />}>
          {!signal.researcher_extraction ? <p className="muted">Waiting for extraction.</p> : (
            <div className="extraction">
              <FactGroup title="Claims" values={signal.researcher_extraction.claims?.map((claim) => claim.text)} />
              <FactGroup title="Entities" values={signal.researcher_extraction.entities?.map((entity) => entity.text + (entity.type ? " - " + entity.type : ""))} />
              <FactGroup title="Numbers" values={signal.researcher_extraction.numbers?.map((number) => number.text)} />
            </div>
          )}
        </Panel>
        <Panel title="Related signals" label={<DataLabel kind="machine" />}>
          {!signal.neighbors?.length ? <p className="muted">No similarity edges have been materialized yet.</p> : (
            <div className="neighbor-list">
              {signal.neighbors.map((edge, index) => (
                <Link to={"/signals/" + (edge.target_signal_id || edge.target_id)} className="neighbor" key={edge.id || index}>
                  <span>{edge.title || "Related signal"}</span>
                  <strong>{Math.round(edge.score * 100)}%</strong>
                </Link>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <aside className="detail-aside">
        <Panel title="Evidence state">
          <Metric label="Evidence revisions" value={signal.evidence_snapshots?.length ?? 0} />
          <Metric label="Active highlights" value={signal.highlights?.filter((item) => item.active !== false && !item.suppressed).length ?? 0} />
          <Metric label="Embeddings" value={signal.embeddings?.length ?? 0} />
          <Metric label="Similarity edges" value={signal.neighbors?.length ?? 0} />
        </Panel>
        <Panel title="Document identity" label={<DataLabel kind="source" />}>
          <dl className="definition-list">
            <div><dt>Document</dt><dd>{signal.document_id || "Pending"}</dd></div>
            <div><dt>Version</dt><dd>{signal.document_version?.id || "Pending"}</dd></div>
            <div><dt>Content hash</dt><dd className="mono">{signal.document_version?.content_hash?.slice(0, 18) || "Pending"}</dd></div>
          </dl>
        </Panel>
      </aside>
    </div>
  );
}

function FactGroup({ title, values }: { title: string; values?: string[] }) {
  return (
    <div><h3>{title}</h3>{values?.length ? <ul className="tag-list">{values.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p className="muted">None extracted</p>}</div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="metric"><strong>{value}</strong><span>{label}</span></div>;
}

function SourceView({ signal, reload }: { signal: SignalDetail; reload: () => Promise<void> }) {
  const container = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<{ start: number; end: number; text: string }>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const text = signal.document_version?.normalized_text || "";
  const highlights = signal.highlights ?? [];

  function captureSelection() {
    const selected = window.getSelection();
    const range = selected?.rangeCount ? selected.getRangeAt(0) : undefined;
    if (!selected || !range || selected.isCollapsed || !container.current || !container.current.contains(range.commonAncestorContainer)) {
      setSelection(undefined);
      return;
    }
    const before = document.createRange();
    before.selectNodeContents(container.current);
    before.setEnd(range.startContainer, range.startOffset);
    const start = before.toString().length;
    const value = range.toString();
    setSelection({ start, end: start + value.length, text: value });
  }

  async function addHighlight(event: ReactMouseEvent) {
    event.preventDefault();
    if (!selection) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.signals.addHighlight(signal.id, selection.start, selection.end, selection.text);
      window.getSelection()?.removeAllRanges();
      setSelection(undefined);
      await reload();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try { await action(); await reload(); } catch (reason) { setError(reason); } finally { setBusy(false); }
  }

  if (!signal.document_version) {
    return <Panel><p className="muted">The immutable document version will appear after fetching completes.</p></Panel>;
  }

  return (
    <div className="source-layout">
      <Panel
        title={signal.document_version.title || "Normalized source"}
        label={<DataLabel kind="source" />}
        className="reader-panel"
      >
        <div className="reader-meta">
          <span>Retrieved {formatDate(signal.document_version.retrieved_at)}</span>
          <span>{signal.document_version.media_type || "text"}</span>
        </div>
        <div className="reader-instruction">Select text to create an exact-span human highlight.</div>
        {selection && (
          <div className="selection-toolbar">
            <span>{selection.text.slice(0, 48)}{selection.text.length > 48 ? "..." : ""}</span>
            <button className="button button-primary button-small" disabled={busy} onMouseDown={(event) => void addHighlight(event)}>Highlight selection</button>
          </div>
        )}
        <div ref={container} className="source-text" onMouseUp={captureSelection}>
          <HighlightedText text={text} highlights={highlights} />
        </div>
      </Panel>
      <aside className="highlight-rail">
        {Boolean(error) && <ErrorNotice error={error} />}
        <p className="eyebrow">Evidence spans</p>
        {!highlights.length && <p className="muted">No highlights yet.</p>}
        {highlights.map((highlight) => (
          <article className={"highlight-card " + highlight.kind} key={highlight.id}>
            <div><DataLabel kind={highlight.kind === "human" ? "human" : "machine"} />{highlight.suppressed && <span className="status">suppressed</span>}</div>
            <q>{highlight.text}</q>
            <small>Characters {highlight.start_offset}{highlight.end_offset}</small>
            {highlight.kind === "human" ? (
              <button className="text-button danger" disabled={busy} onClick={() => void mutate(() => api.signals.removeHighlight(signal.id, highlight.id))}>Remove</button>
            ) : (
              <button className="text-button" disabled={busy} onClick={() => void mutate(() => api.signals.suppressAuto(signal.id, highlight.id, !highlight.suppressed))}>{highlight.suppressed ? "Restore" : "Suppress"}</button>
            )}
          </article>
        ))}
      </aside>
    </div>
  );
}

function HighlightedText({ text, highlights }: { text: string; highlights: Highlight[] }) {
  const spans = useMemo(() => {
    const accepted: Highlight[] = [];
    for (const item of highlights
      .filter((highlight) => highlight.active !== false && !highlight.suppressed)
      .sort((a, b) => a.start_offset - b.start_offset || b.end_offset - a.end_offset)) {
      if (item.start_offset < 0 || item.end_offset > text.length || item.end_offset <= item.start_offset) continue;
      if (accepted.some((existing) => item.start_offset < existing.end_offset && item.end_offset > existing.start_offset)) continue;
      accepted.push(item);
    }
    return accepted.sort((a, b) => a.start_offset - b.start_offset);
  }, [text, highlights]);

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  spans.forEach((highlight) => {
    nodes.push(text.slice(cursor, highlight.start_offset));
    nodes.push(<mark key={highlight.id} className={"mark-" + highlight.kind} title={(highlight.kind === "human" ? "Human" : "Auto") + " highlight"}>{text.slice(highlight.start_offset, highlight.end_offset)}</mark>);
    cursor = highlight.end_offset;
  });
  nodes.push(text.slice(cursor));
  return <>{nodes}</>;
}

function Provenance({ signal }: { signal: SignalDetail }) {
  return (
    <div className="detail-grid">
      <Panel title="Immutable evidence snapshots" label={<DataLabel kind="machine" />}>
        {!signal.evidence_snapshots?.length ? <p className="muted">No snapshots yet.</p> : (
          <ol className="timeline">
            {[...signal.evidence_snapshots].reverse().map((snapshot) => (
              <li key={snapshot.id}>
                <div><strong>Revision {snapshot.revision ?? ""}</strong><span>{formatDate(snapshot.created_at)}</span></div>
                <dl className="definition-list compact">
                  <div><dt>Recipe</dt><dd>{snapshot.recipe_version || ""}</dd></div>
                  <div><dt>Prompt hash</dt><dd className="mono">{snapshot.prompt_hash?.slice(0, 16) || ""}</dd></div>
                  <div><dt>Config hash</dt><dd className="mono">{snapshot.config_hash?.slice(0, 16) || ""}</dd></div>
                </dl>
              </li>
            ))}
          </ol>
        )}
      </Panel>
      <aside className="detail-aside">
        <Panel title="Vector artifacts">
          {!signal.embeddings?.length ? <p className="muted">No embeddings yet.</p> : signal.embeddings.map((embedding) => (
            <div className="artifact-row" key={embedding.id}>
              <span><strong>{embedding.kind.replaceAll("_", " ")}</strong><small>{embedding.model_profile}</small></span>
              <code>{embedding.dimensions}d</code>
            </div>
          ))}
        </Panel>
        <Panel title="Processing attempts">
          {!signal.stage_attempts?.length ? <p className="muted">No attempt history returned.</p> : signal.stage_attempts.map((attempt) => (
            <div className="artifact-row" key={attempt.id}>
              <span><strong>{attempt.stage}</strong><small>Attempt {attempt.attempt}</small></span>
              <StatusBadge status={attempt.status} />
            </div>
          ))}
        </Panel>
      </aside>
    </div>
  );
}
