import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataLabel, Pipeline, StatusBadge } from "./ui";

describe("evidence language", () => {
  it("keeps provenance categories explicit", () => {
    render(
      <>
        <DataLabel kind="human" />
        <DataLabel kind="source" />
        <DataLabel kind="machine" />
      </>,
    );
    expect(screen.getByText("Human input")).toBeInTheDocument();
    expect(screen.getByText("Source evidence")).toBeInTheDocument();
    expect(screen.getByText("Machine-derived data")).toBeInTheDocument();
  });

  it("shows the complete asynchronous pipeline", () => {
    render(<Pipeline status="embedding" />);
    expect(screen.getByLabelText("Processing: embedding")).toBeInTheDocument();
    expect(screen.getByText("accepted").closest("li")).toHaveClass("done");
    expect(screen.getByText("embedding").closest("li")).toHaveClass("current");
    expect(screen.getByText("ready").closest("li")).toHaveClass("waiting");
  });

  it("renders status without changing its meaning", () => {
    render(<StatusBadge status="source_failed" />);
    expect(screen.getByText("source failed")).toBeInTheDocument();
  });
});
