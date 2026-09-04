import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ArticleGradeCard, GradingBoard } from "../lib/types";
import { GradingPage } from "./GradingPage";

const mocks = vi.hoisted(() => ({
  board: vi.fn(),
  update: vi.fn(),
  thumbnail: vi.fn(),
}));

vi.mock("../lib/api", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    api: {
      grading: mocks,
    },
  };
});

const article: ArticleGradeCard = {
  id: "signal-1",
  url: "https://example.test/article",
  canonical_url: "https://example.test/article",
  title: "Reliable evidence for storm resilience",
  thumbnail_url: null,
  grade: null,
  updated_at: "2026-09-04T12:00:00Z",
  revision: "revision-1",
};

function board(overrides: Partial<GradingBoard> = {}): GradingBoard {
  return {
    ungraded: [article],
    tiers: { "1": [], "2": [], "3": [], "4": [] },
    revision: "board-1",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <GradingPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.board.mockReset();
  mocks.update.mockReset();
  mocks.thumbnail.mockReset();
  mocks.board.mockResolvedValue(board());
  mocks.thumbnail.mockRejectedValue(new Error("No thumbnail"));
});

afterEach(cleanup);

describe("shared article grading board", () => {
  it("renders the ungraded rail and four ordered grade tiers", async () => {
    renderPage();

    expect(await screen.findByRole("region", { name: "Ungraded articles, 1 article" }))
      .toHaveTextContent(article.title);
    const tierHeadings = screen.getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(tierHeadings).toEqual(["Ungraded", "Essential", "Strong", "Useful", "Limited"]);
  });

  it("moves an article optimistically and persists its expected revision", async () => {
    const user = userEvent.setup();
    let resolveUpdate!: (value: ArticleGradeCard) => void;
    mocks.update.mockReturnValue(new Promise((resolve) => {
      resolveUpdate = resolve;
    }));
    renderPage();

    const ungraded = await screen.findByRole("region", { name: "Ungraded articles, 1 article" });
    await user.click(within(ungraded).getByRole("button", { name: "Assign grade 4" }));

    const gradeFour = screen.getByRole("region", { name: "Grade 4: Essential, 1 article" });
    expect(within(gradeFour).getByText(article.title)).toBeInTheDocument();
    expect(mocks.update).toHaveBeenCalledWith("signal-1", 4, "revision-1");

    resolveUpdate({ ...article, grade: 4, revision: "revision-2" });
    expect(await screen.findByText("Graded “" + article.title + "” as 4.")).toBeInTheDocument();
  });

  it("rolls the card back when persistence fails", async () => {
    const user = userEvent.setup();
    mocks.update.mockRejectedValue(new Error("Backend unavailable"));
    renderPage();

    const ungraded = await screen.findByRole("region", { name: "Ungraded articles, 1 article" });
    await user.click(within(ungraded).getByRole("button", { name: "Assign grade 2" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
    expect(screen.getByRole("region", { name: "Ungraded articles, 1 article" }))
      .toHaveTextContent(article.title);
  });

  it("supports keyboard grading shortcuts on a focused card", async () => {
    mocks.update.mockResolvedValue({ ...article, grade: 3, revision: "revision-2" });
    renderPage();

    const card = await screen.findByRole("article", {
      name: article.title + ", ungraded",
    });
    card.focus();
    fireEvent.keyDown(card, { key: "3" });

    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith("signal-1", 3, "revision-1"));
    expect(screen.getByRole("region", { name: "Grade 3: Strong, 1 article" }))
      .toHaveTextContent(article.title);
  });
});
