import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Alert, Category } from "../types";
import { AlertList } from "./AlertList";
import { StatusBadge } from "./StatusBadge";

const alert = (over: Partial<Alert> = {}): Alert => ({
  id: 1,
  node_id: "node-3",
  category: "Combined",
  priority: "High",
  max_priority: "High",
  start_ts: "2018-01-07T12:00:00",
  last_ts: "2018-01-07T14:00:00",
  end_ts: null,
  status: "active",
  confidence: 0.8,
  explanation: "Combined anomaly: infrastructure evidence 0.93.",
  ...over,
});

describe("StatusBadge", () => {
  it.each<[Category, string]>([
    ["Normal", "Normal"],
    ["Infrastructure", "Infrastructure"],
    ["Quality", "Quality"],
    ["Combined", "Combined"],
  ])("shows text, icon and accessible label for %s", (cat, text) => {
    const { container } = render(<StatusBadge category={cat} />);
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeNull(); // icon, not colour alone
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", cat);
  });

  it("adds a priority tag with text for alerts", () => {
    render(<StatusBadge category="Quality" priority="Critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Quality, Critical priority");
  });

  it("does not show priority for Normal", () => {
    render(<StatusBadge category="Normal" priority="Low" />);
    expect(screen.queryByText("Low")).toBeNull();
  });
});

describe("AlertList", () => {
  it("shows loading, error and empty states", () => {
    const { rerender } = render(<AlertList alerts={[]} loading />);
    expect(screen.getByText(/Loading alerts/)).toBeInTheDocument();
    rerender(<AlertList alerts={[]} error="503 service unavailable" />);
    expect(screen.getByRole("alert")).toHaveTextContent("503 service unavailable");
    rerender(<AlertList alerts={[]} />);
    expect(screen.getByText(/No alerts yet/)).toBeInTheDocument();
  });

  it("lists alerts with node name, status text and explanation, and selects on click", () => {
    const onSelect = vi.fn();
    render(
      <AlertList
        alerts={[alert(), alert({ id: 2, node_id: "node-5", category: "Quality", priority: "Medium", status: "closed", end_ts: "2018-01-07T16:00:00", explanation: "Quality anomaly." })]}
        nodeNames={{ "node-3": "Sathuvachari Main", "node-5": "Old Town Junction" }}
        onSelect={onSelect}
      />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Sathuvachari Main")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Closed")).toBeInTheDocument();
    expect(screen.getByText(/infrastructure evidence 0.93/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Open Old Town Junction"));
    expect(onSelect).toHaveBeenCalledWith("node-5");
  });

  it("respects the limit", () => {
    render(<AlertList alerts={[alert({ id: 1 }), alert({ id: 2 }), alert({ id: 3 })]} limit={2} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});
