import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SignalDetail } from "./types";
import { api } from "./api";

const aggregate: SignalDetail = {
  id: "signal-1",
  url: "https://example.com/submitted",
  canonical_url: "https://example.com/article",
  description_verbatim: "Research note",
  status: "ready",
  document_version_id: "document-version-1",
  document_id: "document-1",
  document_version: {
    id: "document-version-1",
    canonical_url: "https://example.com/article",
    title: "Article title",
    normalized_text: "Article body",
  },
  researcher_extraction: {
    claims: [{ text: "Research note" }],
  },
  nlp_artifact: {
    entities: [{ text: "Example Org" }],
  },
  highlights: [],
  comments: [],
  evidence_snapshots: [],
  embeddings: [],
  neighbors: [],
  stage_attempts: [],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("aggregate signal detail API", () => {
  it("loads the complete detail with one request and does not call legacy subresources", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(aggregate), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(api.signals.get("signal-1")).resolves.toEqual(aggregate);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const requestedUrls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(requestedUrls).toEqual(["/v1/signals/signal-1"]);
    expect(requestedUrls.join(" ")).not.toMatch(
      /\/documents\/|\/highlights|\/neighbors|\/comments/,
    );
  });
});
