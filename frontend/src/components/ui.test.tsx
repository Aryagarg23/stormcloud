import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataLabel, Pipeline, StatusBadge } from "./ui";

describe("researcher-facing language", () => {
  it("uses plain data-source labels", () => {
    render(
      <>
        <DataLabel kind="human" />
        <DataLabel kind="source" />
        <DataLabel kind="machine" />
      </>,
    );
    expect(screen.getByText("Researcher")).toBeInTheDocument();
    expect(screen.getByText("Article")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
  });

  it("shows the complete asynchronous pipeline", () => {
    render(<Pipeline status="embedding" />);
    expect(screen.getByLabelText("Processing: embedding")).toBeInTheDocument();
    expect(screen.getByText("queued").closest("li")).toHaveClass("done");
    expect(screen.getByText("index").closest("li")).toHaveClass("current");
    expect(screen.getByText("ready").closest("li")).toHaveClass("waiting");
  });

  it("renders status without changing its meaning", () => {
    render(<StatusBadge status="source_failed" />);
    expect(screen.getByText("source failed")).toBeInTheDocument();
  });
});
