import {
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useParams } from "react-router-dom";
import {
  ErrorNotice,
  formatDate,
  Loading,
  Panel,
  StatusBadge,
} from "../components/ui";
import { api } from "../lib/api";
import { useResource } from "../hooks/useResource";
import type { Highlight, SignalDetail } from "../lib/types";

type Tab = "article" | "analysis" | "comments";

export function SignalPage() {
  const { id = "" } = useParams();
  const resource = useResource(() => api.signals.get(id), [id]);
  const { data: signal, error, loading, reload } = resource;
  const [tab, setTab] = useState<Tab>("article");
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

  const tabs: Array<[Tab, string]> = [
    ["article", "Article & annotations"],
    ...(signal.researcher_extraction || signal.nlp_artifact
      ? [["analysis", "Analysis"] as [Tab, string]]
      : []),
    ["comments", "Comments"],

  ];
  return (
    <>
      <header className="signal-record-header">
        <div className="signal-record-meta">
          <span>Submitted {formatDate(signal.created_at)}</span>
          <StatusBadge status={signal.status} />
        </div>
        <h1>{signal.description_verbatim}</h1>
        <div className="button-row">
          <a className="button" href={signal.canonical_url || signal.url} target="_blank" rel="noreferrer">
            Open article
          </a>
          {signal.status === "failed" && signal.failure?.retryable !== false && (
            <button className="button" disabled={retrying} onClick={() => void retry()}>
              {retrying ? "Retrying..." : "Retry"}
            </button>
          )}
        </div>
      </header>
      {signal.status !== "ready" && signal.status !== "failed" && (
        <p className="processing-note" role="status">
          Processing continues in the background. This page updates automatically.
        </p>
      )}
      {Boolean(mutationError) && <ErrorNotice error={mutationError} />}
      {signal.failure && (
        <div className="error-notice" role="alert">
          <strong>{signal.failure.stage ? "Failed during " + signal.failure.stage : "Processing failed"}</strong>
          <span>{signal.failure.detail}</span>
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Signal detail">
        {tabs.map(([value, label]) => (
          <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
            {label}
            {value === "comments" && signal.comments?.length ? ` (${signal.comments.length})` : ""}
          </button>
        ))}
      </div>
      {tab === "article" && (
        <>
          <SourceView signal={signal} reload={reload} />
          {Boolean(signal.neighbors?.length) && <RelatedSignals signal={signal} />}
        </>
      )}
      {tab === "analysis" && <Analysis signal={signal} />}
      {tab === "comments" && <Comments signal={signal} reload={reload} />}
    </>
  );
}

function Analysis({ signal }: { signal: SignalDetail }) {
  const extraction = signal.researcher_extraction;
  const nlp = signal.nlp_artifact;
  const features = nlp?.payload?.features ?? [];
  const unique = (values: Array<string | undefined>) => [...new Set(values.filter((value): value is string => Boolean(value)))];
  const groups = [
    { title: "Claims", values: unique(extraction?.claims?.map((item) => item.text) ?? []) },
    { title: "People & organizations", values: unique([...(nlp?.entities?.map((item) => item.text) ?? []), ...features.filter((item) => item.kind === "entity").map((item) => item.text)]) },
    { title: "Dates", values: unique([...(extraction?.dates?.map((item) => item.text) ?? []), ...(nlp?.dates?.map((item) => item.text) ?? []), ...features.filter((item) => item.kind === "date").map((item) => item.text)]) },
    { title: "Numbers", values: unique([...(extraction?.numbers?.map((item) => item.text) ?? []), ...(nlp?.numbers?.map((item) => item.text) ?? []), ...features.filter((item) => item.kind === "number").map((item) => item.text)]) },
    { title: "Topics", values: unique(nlp?.noun_phrases ?? features.filter((item) => item.kind === "noun_phrase").map((item) => item.text)) },
  ].filter((group) => group.values.length);

  if (!groups.length) return <p className="muted">No structured findings were generated.</p>;

  return (
    <div className="analysis-grid">
      {groups.map((group) => (
        <section key={group.title}>
          <h2>{group.title}</h2>
          <ul>{group.values.map((value) => <li key={value}>{value}</li>)}</ul>
        </section>
      ))}
    </div>
  );
}

function RelatedSignals({ signal }: { signal: SignalDetail }) {
  return (
    <section className="related-signals">
      <h2>Related signals</h2>
      <div className="neighbor-list">
        {signal.neighbors?.map((edge, index) => (
          <Link to={"/signals/" + (edge.target_signal_id || edge.target_id)} className="neighbor" key={edge.id || index}>
            <span>{edge.title || "Related signal"}</span>
            <span>{Math.round(edge.score * 100)}% match</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Comments({ signal, reload }: { signal: SignalDetail; reload: () => Promise<void> }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const comment = body.trim();
    if (!comment) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.signals.addComment(signal.id, comment);
      setBody("");
      await reload();
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="comments-layout">
      <Panel title="Comments">
        {Boolean(error) && <ErrorNotice error={error} />}
        <form className="comment-form" onSubmit={submit}>
          <label>
            Add a comment
            <textarea
              rows={3}
              maxLength={10000}
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="form-actions">
            <button className="button button-primary" disabled={busy || !body.trim()}>
              {busy ? "Adding..." : "Add comment"}
            </button>
          </div>
        </form>
        <div className="comment-list" aria-live="polite">
          {!signal.comments?.length && <p className="muted">No comments.</p>}
          {signal.comments?.map((comment) => (
            <article className="comment" key={comment.id}>
              <header>
                <strong>{comment.author.email}</strong>
                <time>{formatDate(comment.created_at)}</time>
              </header>
              <p>{comment.body}</p>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function SourceView({ signal, reload }: { signal: SignalDetail; reload: () => Promise<void> }) {
  const container = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<{ start: number; end: number; text: string }>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const text = signal.document_version?.normalized_text || "";
  const highlights = (signal.highlights ?? []).filter((highlight) => highlight.active !== false);

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
    return <Panel><p className="muted">The article will appear after processing.</p></Panel>;
  }

  return (
    <div className="source-layout">
      <Panel
        title={signal.document_version.title || "Article"}
        className="reader-panel"
      >
        <div className="reader-instruction">Select text to add an annotation.</div>
        {selection && (
          <div className="selection-toolbar">
            <span>{selection.text.slice(0, 48)}{selection.text.length > 48 ? "..." : ""}</span>
            <button className="button button-primary button-small" disabled={busy} onMouseDown={(event) => void addHighlight(event)}>Add annotation</button>
          </div>
        )}
        <div ref={container} className="source-text" onMouseUp={captureSelection}>
          <HighlightedText text={text} highlights={highlights} />
        </div>
      </Panel>
      <aside className="highlight-rail">
        {Boolean(error) && <ErrorNotice error={error} />}
        <p className="eyebrow">Annotations</p>
        {!highlights.length && <p className="muted">No annotations.</p>}
        {highlights.map((highlight) => (
          <article className={"highlight-card " + highlight.kind} key={highlight.id}>
            <div>
              <span className="annotation-kind">{highlight.kind === "human" ? "Added by researcher" : "Suggested"}</span>
              {highlight.suppressed && <span className="status">hidden</span>}
            </div>
            <q>{highlight.text}</q>
            {highlight.kind === "human" ? (
              <button className="text-button danger" disabled={busy} onClick={() => void mutate(() => api.signals.removeHighlight(signal.id, highlight.id))}>Remove</button>
            ) : (
              <button className="text-button" disabled={busy} onClick={() => void mutate(() => api.signals.suppressAuto(signal.id, highlight.id, !highlight.suppressed))}>{highlight.suppressed ? "Show" : "Hide"}</button>
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
