import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNotice, Loading, PageHeader, Panel, Pipeline, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import type { Operation, PipelineStatus } from "../lib/types";

export function OperationPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [operation, setOperation] = useState<Operation>();
  const [error, setError] = useState<unknown>();

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    async function poll() {
      try {
        const next = await api.operations.get(id);
        if (!active) return;
        setOperation(next);
        setError(undefined);
        if (next.status === "succeeded" || next.status === "ready") {
          const aggregate = next.aggregate_id;
          if (aggregate) {
            window.setTimeout(() => navigate("/" + (next.aggregate_type === "bundle" ? "bundles/" : "signals/") + aggregate, { replace: true }), 650);
            return;
          }
        }
        if (next.status !== "failed") timer = window.setTimeout(poll, 1800);
      } catch (reason) {
        if (!active) return;
        setError(reason);
        timer = window.setTimeout(poll, 4000);
      }
    }
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, [id, navigate]);

  const stage = (operation?.stage || operation?.status || "accepted") as PipelineStatus;

  return (
    <>
      <PageHeader eyebrow="Asynchronous operation" title="Building the evidence record" description="You can leave this page. Processing continues in the background." />
      {Boolean(error) && <ErrorNotice error={error} />}
      {!operation && !error && <Loading label="Checking operation" />}
      {operation && (
        <Panel className="operation-panel">
          <div className="operation-title">
            <div><p className="eyebrow">Operation</p><code>{operation.id}</code></div>
            <StatusBadge status={operation.status} />
          </div>
          <Pipeline status={stage} />
          {operation.detail && <p className="muted">{operation.detail}</p>}
          {Boolean(operation.error) && <div className="error-notice" role="alert">{operation.error}</div>}
          <div className="form-actions">
            <Link className="button" to="/">Back to signals</Link>
            {operation.aggregate_id && (
              <Link className="button button-primary" to={"/" + (operation.aggregate_type === "bundle" ? "bundles/" : "signals/") + operation.aggregate_id}>Open record</Link>
            )}
          </div>
        </Panel>
      )}
    </>
  );
}
