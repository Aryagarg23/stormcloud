import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SignalDetail } from "../lib/types";
import { SignalPage } from "./SignalPage";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  retry: vi.fn(),
  addComment: vi.fn(),
  addHighlight: vi.fn(),
  removeHighlight: vi.fn(),
  suppressAuto: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: {
    signals: mocks,
  },
}));

const signal: SignalDetail = {
  id: "signal-1",
  url: "https://example.com/submitted",
  canonical_url: "https://example.com/article",
  description_verbatim: "Research note for the team",
  status: "ready",
  created_at: "2026-09-04T12:00:00Z",
  document_id: "internal-document-id",
  document_version_id: "internal-document-version-id",
  operation_id: "internal-operation-id",
  document_version: {
    id: "internal-document-version-id",
    canonical_url: "https://example.com/article",
    title: "Readable article title",
    media_type: "text/plain",
    content_hash: "internal-content-hash",
    normalized_text: "Important evidence appears here.",
    retrieved_at: "2026-09-04T12:00:00Z",
  },
  researcher_extraction: {
    claims: [{ text: "Claim Alpha" }],
    numbers: [{ text: "42" }],
    dates: [{ text: "2026" }],
  },
  nlp_artifact: {
    entities: [{ text: "Example Org" }],
    noun_phrases: ["climate resilience"],
  },
  highlights: [
    {
      id: "highlight-1",
      kind: "human",
      start_offset: 0,
      end_offset: 18,
      text: "Important evidence",
      active: true,
      suppressed: false,
    },
  ],
  comments: [
    {
      id: "comment-1",
      signal_id: "signal-1",
      body: "Shared research comment",
      author: { id: "member-1", email: "member@example.com" },
      created_at: "2026-09-04T12:30:00Z",
    },
  ],
  evidence_snapshots: [
    {
      id: "internal-evidence-id",
      revision: 1,
      evidence_text: "internal evidence",
    },
  ],
  embeddings: [
    {
      id: "internal-embedding-id",
      kind: "evidence",
      model_profile: "qwen",
      dimensions: 1024,
    },
  ],
  neighbors: [],
  stage_attempts: [
    {
      id: "internal-stage-id",
      stage: "fetch",
      status: "succeeded",
      attempt: 1,
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/signals/signal-1"]}>
      <Routes>
        <Route path="/signals/:id" element={<SignalPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.get.mockResolvedValue(signal);
});

afterEach(cleanup);

describe("researcher-facing signal page", () => {
  it("shows the three useful views and omits internal record and pipeline UI", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("tab", { name: "Article & annotations" }))
      .toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Analysis" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Comments (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Summary" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "History" })).not.toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Readable article title" }))
      .toBeInTheDocument();
    expect(screen.getByText("Important evidence", { selector: "mark" }))
      .toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Analysis" }));
    expect(screen.getByText("Claim Alpha")).toBeInTheDocument();
    expect(screen.getByText("Example Org")).toBeInTheDocument();
    expect(screen.getByText("climate resilience")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Comments (1)" }));
    expect(screen.getByText("Shared research comment")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();

    const rendered = document.body.textContent ?? "";
    expect(rendered).not.toContain("internal-document-id");
    expect(rendered).not.toContain("internal-document-version-id");
    expect(rendered).not.toContain("internal-operation-id");
    expect(rendered).not.toContain("internal-evidence-id");
    expect(rendered).not.toContain("internal-embedding-id");
    expect(rendered).not.toContain("internal-stage-id");
    expect(rendered.toLowerCase()).not.toContain("pipeline");
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledWith("signal-1");
  });
});
