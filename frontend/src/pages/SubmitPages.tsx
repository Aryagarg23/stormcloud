import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorNotice, PageHeader, Panel } from "../components/ui";
import { api } from "../lib/api";

function operationTarget(result: {
  operation_id?: string;
  status_url?: string;
  aggregate_id?: string;
  id?: string;
  signal_id?: string;
  bundle_id?: string;
}, type: "signal" | "bundle"): string {
  const operationId = result.operation_id ||
    (result.status_url ? result.status_url.split("/").filter(Boolean).at(-1) : undefined);
  if (operationId) return "/operations/" + operationId;
  const aggregateId = result.aggregate_id || result.signal_id || result.bundle_id || result.id;
  return type === "signal" ? "/signals/" + aggregateId : "/bundles/" + aggregateId;
}

export function SubmitSignalPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      navigate(operationTarget(await api.signals.create(url, description), "signal"));
    } catch (reason) {
      setError(reason);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="New signal"
        actions={<Link className="button" to="/bundles/new">New bundle</Link>}
      />
      <div className="form-layout">
        <Panel title="Source and observation" label={<span className="data-label data-label-human">Human input</span>}>
          {Boolean(error) && <ErrorNotice error={error} />}
          <form className="stacked-form" onSubmit={submit}>
            <label>
              Source URL
              <input type="url" placeholder="https://example.com/research" required value={url} onChange={(event) => setUrl(event.target.value)} />
              <small>Existing articles are reused; this signal stays separate.</small>
            </label>
            <label>
              Signal
              <textarea rows={8} required minLength={3} placeholder="What did you notice, and why does it matter?" value={description} onChange={(event) => setDescription(event.target.value)} />
              <small>{description.length} characters</small>
            </label>
            <div className="form-actions">
              <Link to="/" className="button">Cancel</Link>
              <button className="button button-primary" disabled={busy}>{busy ? "Submitting..." : "Submit signal"}</button>
            </div>
          </form>
        </Panel>
      </div>
    </>
  );
}

interface DraftItem {
  key: string;
  url: string;
  note: string;
}

function blankItem(): DraftItem {
  return { key: crypto.randomUUID(), url: "", note: "" };
}

export function SubmitBundlePage() {
  const navigate = useNavigate();
  const [thesis, setThesis] = useState("");
  const [ordered, setOrdered] = useState(true);
  const [items, setItems] = useState<DraftItem[]>([blankItem(), blankItem()]);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  function patch(index: number, value: Partial<DraftItem>) {
    setItems((current) => current.map((item, at) => at === index ? { ...item, ...value } : item));
  }
  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= items.length) return;
    setItems((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }
  function remove(index: number) {
    if (items.length <= 2) return;
    setItems((current) => current.filter((_, at) => at !== index));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const result = await api.bundles.create({
        thesis: thesis.trim() || undefined,
        ordered,
        items: items.map((item, position) => ({
          url: item.url,
          note: item.note.trim() || undefined,
          position,
        })),
      });
      navigate(operationTarget(result, "bundle"));
    } catch (reason) {
      setError(reason);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="New bundle"
      />
      {Boolean(error) && <ErrorNotice error={error} />}
      <form className="bundle-form" onSubmit={submit}>
        <Panel title="Bundle framing" label={<span className="data-label data-label-human">Human input</span>}>
          <label>
            Bundle thesis <span className="optional">optional</span>
            <textarea rows={3} placeholder="What question or argument connects these sources?" value={thesis} onChange={(event) => setThesis(event.target.value)} />
          </label>
          <label className="switch-row">
            <input type="checkbox" checked={ordered} onChange={(event) => setOrdered(event.target.checked)} />
            <span><strong>Ordered</strong><small>Keep this source order.</small></span>
          </label>
        </Panel>

        <div className="bundle-items-heading">
          <div><p className="eyebrow">Source sequence</p><h2>{items.length} items</h2></div>
          <button type="button" className="button" onClick={() => setItems((current) => [...current, blankItem()])}>Add source</button>
        </div>
        <ol className="bundle-editor">
          {items.map((item, index) => (
            <li key={item.key} className="bundle-item">
              <div className="position">{index + 1}</div>
              <div className="bundle-item-fields">
                <label>Source URL<input type="url" required placeholder="https://example.com" value={item.url} onChange={(event) => patch(index, { url: event.target.value })} /></label>
                <label>Item note <span className="optional">optional</span><textarea rows={2} placeholder="Why this source belongs in the bundle" value={item.note} onChange={(event) => patch(index, { note: event.target.value })} /></label>
              </div>
              <div className="reorder" aria-label={"Reorder item " + (index + 1)}>
                <button type="button" aria-label="Move up" disabled={index === 0} onClick={() => move(index, -1)}>Up</button>
                <button type="button" aria-label="Move down" disabled={index === items.length - 1} onClick={() => move(index, 1)}>Down</button>
                <button type="button" aria-label="Remove item" disabled={items.length <= 2} onClick={() => remove(index)}>X</button>
              </div>
            </li>
          ))}
        </ol>
        <div className="form-actions sticky-actions">
          <Link to="/bundles" className="button">Cancel</Link>
          <button className="button button-primary" disabled={busy}>{busy ? "Creating..." : "Create bundle"}</button>
        </div>
      </form>
    </>
  );
}
