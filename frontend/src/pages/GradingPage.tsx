import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useResource } from "../hooks/useResource";
import { api, ApiError } from "../lib/api";
import type {
  ArticleGrade,
  ArticleGradeCard,
  GradeTierKey,
  GradingBoard,
} from "../lib/types";
import { EmptyState, ErrorNotice, Loading, PageHeader } from "../components/ui";
import "./GradingPage.css";

const tiers: Array<{
  grade: ArticleGrade;
  key: GradeTierKey;
  name: string;
  description: string;
}> = [
  { grade: 4, key: "4", name: "Essential", description: "Foundational evidence worth returning to." },
  { grade: 3, key: "3", name: "Strong", description: "High-value evidence with clear utility." },
  { grade: 2, key: "2", name: "Useful", description: "Helpful context or supporting evidence." },
  { grade: 1, key: "1", name: "Limited", description: "Low-signal, narrow, or weak evidence." },
];

function articleFrom(board: GradingBoard, id: string): ArticleGradeCard | undefined {
  return [
    ...board.ungraded,
    ...board.tiers["1"],
    ...board.tiers["2"],
    ...board.tiers["3"],
    ...board.tiers["4"],
  ].find((article) => article.id === id);
}

function placeArticle(
  board: GradingBoard,
  article: ArticleGradeCard,
  grade: ArticleGrade | null,
): GradingBoard {
  const without = (items: ArticleGradeCard[]) =>
    items.filter((candidate) => candidate.id !== article.id);
  const next: GradingBoard = {
    ...board,
    ungraded: without(board.ungraded),
    tiers: {
      "1": without(board.tiers["1"]),
      "2": without(board.tiers["2"]),
      "3": without(board.tiers["3"]),
      "4": without(board.tiers["4"]),
    },
  };
  const moved = { ...article, grade };
  if (grade === null) {
    next.ungraded = [moved, ...next.ungraded];
  } else {
    const key = String(grade) as GradeTierKey;
    next.tiers[key] = [moved, ...next.tiers[key]];
  }
  return next;
}

function SecureThumbnail({ article }: { article: ArticleGradeCard }) {
  const [src, setSrc] = useState<string>();
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    void api.grading.thumbnail(article.id)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (active) setUnavailable(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [article.id, article.revision]);

  if (!src) {
    return (
      <div className="grade-card-placeholder" aria-hidden="true">
        {unavailable ? <span>SC</span> : <span className="thumbnail-shimmer" />}
      </div>
    );
  }
  return <img className="grade-card-image" src={src} alt="" draggable={false} />;
}

function ArticleCard({
  article,
  pending,
  onGrade,
  onDragStart,
  onDragEnd,
}: {
  article: ArticleGradeCard;
  pending: boolean;
  onGrade: (grade: ArticleGrade | null) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
}) {
  const hostname = useMemo(() => {
    try {
      return new URL(article.canonical_url || article.url).hostname.replace(/^www\./, "");
    } catch {
      return "source";
    }
  }, [article.canonical_url, article.url]);

  return (
    <article
      className={"grade-card" + (pending ? " is-pending" : "")}
      draggable={!pending}
      tabIndex={0}
      aria-busy={pending}
      aria-label={article.title + (article.grade ? ", grade " + article.grade : ", ungraded")}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", article.id);
        onDragStart(article.id);
      }}
      onDragEnd={onDragEnd}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget || pending) return;
        if (["1", "2", "3", "4"].includes(event.key)) {
          event.preventDefault();
          onGrade(Number(event.key) as ArticleGrade);
        } else if (event.key.toLowerCase() === "u" || event.key === "0") {
          event.preventDefault();
          onGrade(null);
        }
      }}
    >
      <SecureThumbnail article={article} />
      <div className="grade-card-body">
        <span className="grade-card-host">{hostname}</span>
        <Link to={"/signals/" + article.id} className="grade-card-title">
          {article.title || "Untitled article"}
        </Link>
        <div className="grade-controls" aria-label={"Grade " + article.title}>
          {[1, 2, 3, 4].map((grade) => (
            <button
              type="button"
              key={grade}
              className={article.grade === grade ? "selected" : ""}
              aria-label={"Assign grade " + grade}
              aria-pressed={article.grade === grade}
              disabled={pending}
              onClick={() => onGrade(grade as ArticleGrade)}
            >
              {grade}
            </button>
          ))}
          {article.grade !== null && (
            <button
              type="button"
              className="ungrade"
              aria-label="Move to ungraded"
              disabled={pending}
              onClick={() => onGrade(null)}
            >
              U
            </button>
          )}
        </div>
      </div>
      {pending && <span className="grade-card-saving">Saving…</span>}
    </article>
  );
}

function DropZone({
  grade,
  label,
  count,
  active,
  onDrop,
  children,
  className = "",
}: {
  grade: ArticleGrade | null;
  label: string;
  count: number;
  active: boolean;
  onDrop: (id: string, grade: ArticleGrade | null) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={"grade-drop-zone " + className + (active ? " drag-active" : "")}
      aria-label={label + ", " + count + (count === 1 ? " article" : " articles")}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onDrop={(event) => {
        event.preventDefault();
        const id = event.dataTransfer.getData("text/plain");
        if (id) onDrop(id, grade);
      }}
    >
      {children}
    </section>
  );
}

export function GradingPage() {
  const { data, error, loading, reload, setData } = useResource(api.grading.board, []);
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const [draggingId, setDraggingId] = useState<string>();
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string }>();
  const inFlightRef = useRef(new Set<string>());

  async function gradeArticle(id: string, grade: ArticleGrade | null) {
    if (!data || inFlightRef.current.has(id)) return;
    const original = articleFrom(data, id);
    if (!original || original.grade === grade) return;

    inFlightRef.current.add(id);
    setPendingIds((current) => new Set(current).add(id));
    setNotice(undefined);
    setData((current) => current ? placeArticle(current, original, grade) : current);

    try {
      const saved = await api.grading.update(id, grade, original.revision);
      setData((current) => current ? placeArticle(current, saved, saved.grade) : current);
      setNotice({
        tone: "success",
        text: saved.grade === null
          ? "Moved “" + saved.title + "” back to ungraded."
          : "Graded “" + saved.title + "” as " + saved.grade + ".",
      });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          setData(await api.grading.board());
          setNotice({
            tone: "error",
            text: "A teammate updated this article first. The shared board has been refreshed.",
          });
        } catch {
          setData((current) => current ? placeArticle(current, original, original.grade) : current);
          setNotice({ tone: "error", text: "The grade conflicted and the board could not refresh." });
        }
      } else {
        setData((current) => current ? placeArticle(current, original, original.grade) : current);
        setNotice({
          tone: "error",
          text: reason instanceof Error ? reason.message : "The grade could not be saved.",
        });
      }
    } finally {
      setPendingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      inFlightRef.current.delete(id);
      setDraggingId(undefined);
    }
  }

  function cards(items: ArticleGradeCard[]) {
    return items.map((article) => (
      <ArticleCard
        key={article.id}
        article={article}
        pending={pendingIds.has(article.id)}
        onGrade={(grade) => void gradeArticle(article.id, grade)}
        onDragStart={setDraggingId}
        onDragEnd={() => setDraggingId(undefined)}
      />
    ));
  }

  if (loading && !data) return <Loading label="Loading the shared grading board" />;
  if (error && !data) return <ErrorNotice error={error} onRetry={() => void reload()} />;
  if (!data) return null;

  const total = data.ungraded.length + tiers.reduce(
    (sum, tier) => sum + data.tiers[tier.key].length,
    0,
  );

  return (
    <>
      <PageHeader
        title="Article grading"
        actions={
          <button className="button button-small" onClick={() => void reload()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      <div className="grading-summary" aria-label="Grading progress">
        <strong>{total - data.ungraded.length} of {total}</strong>
        <span>articles graded</span>
        <div className="grading-progress" aria-hidden="true">
          <span style={{ width: total ? ((total - data.ungraded.length) / total * 100) + "%" : "0%" }} />
        </div>
      </div>

      <div className="grading-notice" aria-live="polite" aria-atomic="true">
        {notice && (
          <div className={notice.tone === "error" ? "error-notice" : "success-notice"} role={notice.tone === "error" ? "alert" : "status"}>
            <span>{notice.text}</span>
            <button className="text-button" onClick={() => setNotice(undefined)}>Dismiss</button>
          </div>
        )}
      </div>

      <DropZone
        grade={null}
        label="Ungraded articles"
        count={data.ungraded.length}
        active={Boolean(draggingId)}
        onDrop={(id, grade) => void gradeArticle(id, grade)}
        className="ungraded-zone"
      >
        <div className="grade-zone-heading">
          <div>
            <p className="eyebrow">Inbox</p>
            <h2>Ungraded</h2>
          </div>
          <span className="grade-count">{data.ungraded.length}</span>
        </div>
        {data.ungraded.length ? (
          <div className="article-rail">{cards(data.ungraded)}</div>
        ) : (
          <div className="grade-inline-empty">Everything has a grade. Drop an article here to reconsider it.</div>
        )}
      </DropZone>

      <div className="tier-list" aria-label="Graded articles by tier">
        {tiers.map((tier) => {
          const items = data.tiers[tier.key];
          return (
            <DropZone
              key={tier.key}
              grade={tier.grade}
              label={"Grade " + tier.grade + ": " + tier.name}
              count={items.length}
              active={Boolean(draggingId && articleFrom(data, draggingId)?.grade !== tier.grade)}
              onDrop={(id, grade) => void gradeArticle(id, grade)}
              className={"tier tier-" + tier.grade}
            >
              <header className="tier-label">
                <strong>{tier.grade}</strong>
                <div>
                  <h2>{tier.name}</h2>
                  <p>{tier.description}</p>
                </div>
                <span className="grade-count">{items.length}</span>
              </header>
              {items.length ? (
                <div className="tier-cards">{cards(items)}</div>
              ) : (
                <div className="grade-inline-empty">Drop articles here or choose grade {tier.grade} on a card.</div>
              )}
            </DropZone>
          );
        })}
      </div>

      {total === 0 && (
        <EmptyState title="No articles to grade">
          Processed signals will appear in the ungraded rail for the entire research team.
        </EmptyState>
      )}
      <p className="grading-footnote">
        Grades are shared with every workspace member. Changes retain editor and revision provenance.
      </p>
    </>
  );
}
