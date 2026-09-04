import type { PropsWithChildren, ReactNode } from "react";
import type { PipelineStatus } from "../lib/types";

export function StatusBadge({ status }: { status: string }) {
  return <span className={"status status-" + status}>{status.replaceAll("_", " ")}</span>;
}

export function DataLabel({
  kind,
}: {
  kind: "human" | "source" | "machine";
}) {
  const labels = {
    human: "Human input",
    source: "Source evidence",
    machine: "Machine-derived data",
  };
  return <span className={"data-label data-label-" + kind}>{labels[kind]}</span>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="lede">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  label,
  children,
  className = "",
}: PropsWithChildren<{
  title?: string;
  label?: ReactNode;
  className?: string;
}>) {
  return (
    <section className={"panel " + className}>
      {(title || label) && (
        <div className="panel-heading">
          {title && <h2>{title}</h2>}
          {label}
        </div>
      )}
      {children}
    </section>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: PropsWithChildren<{ title: string; action?: ReactNode }>) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true">[ ]</div>
      <h2>{title}</h2>
      <div className="muted">{children}</div>
      {action}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="error-notice" role="alert">
      <strong>Could not complete that request.</strong>
      <span>{message}</span>
      {onRetry && <button className="button button-small" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export const pipelineStages: PipelineStatus[] = [
  "accepted",
  "fetching",
  "enriching",
  "embedding",
  "graphing",
  "ready",
];

export function Pipeline({ status }: { status: PipelineStatus }) {
  const current = pipelineStages.indexOf(status);
  return (
    <ol className="pipeline" aria-label={"Processing: " + status}>
      {pipelineStages.map((stage, index) => {
        const state =
          status === "failed"
            ? index < Math.max(current, 1) ? "done" : "waiting"
            : index < current ? "done" : index === current ? "current" : "waiting";
        return (
          <li className={state} key={stage}>
            <span className="pipeline-dot" aria-hidden="true" />
            <span>{stage}</span>
          </li>
        );
      })}
      {status === "failed" && (
        <li className="failed">
          <span className="pipeline-dot" aria-hidden="true" />
          <span>failed</span>
        </li>
      )}
    </ol>
  );
}

export function formatDate(value?: string): string {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
