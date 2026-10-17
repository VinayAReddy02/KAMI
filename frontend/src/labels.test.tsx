import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AlertList } from "./components/AlertList";
import { markerIcon } from "./components/NodeMap";
import { labelsById, nodeIndex, nodeLabel, nodeShort } from "./labels";
import type { Alert } from "./types";

// The fields the API sends for node-4 (config/nodes.json + data/citizen/wards_demo_fictional.json)
const bagayam = { id: "node-4", name: "Bagayam Booster", number: 4, ward: 4, ward_name: "Bagayam" };
const gandhi = { id: "node-2", name: "Gandhi Nagar Tank", number: 2, ward: 2, ward_name: "Gandhi Nagar" };

describe("node labels (same strings as src/kami/live/labels.py)", () => {
  it("builds the full and the short label", () => {
    expect(nodeLabel(bagayam)).toBe("Bagayam Booster (node-4 · Ward 4)");
    expect(nodeShort(bagayam)).toBe("4 · Bagayam");
    expect(nodeShort(gandhi)).toBe("2 · Gandhi Nagar");
  });

  it("falls back to what is known", () => {
    expect(nodeLabel(undefined, "node-9")).toBe("node-9");
    expect(nodeLabel({ id: "node-9" })).toBe("node-9");
    expect(nodeLabel({ id: "x", name: "Test point" })).toBe("Test point (x)");
    expect(nodeShort({ id: "x", name: "Test point" })).toBe("Test point");
    expect(nodeShort(undefined, "node-9")).toBe("node-9");
  });

  it("indexes nodes by id", () => {
    expect(labelsById([bagayam, gandhi])).toEqual({ "node-4": "Bagayam Booster (node-4 · Ward 4)", "node-2": "Gandhi Nagar Tank (node-2 · Ward 2)" });
    expect(nodeIndex([bagayam])["node-4"].ward).toBe(4);
  });
});

describe("components that name a node", () => {
  it("the map marker shows the numbered short label next to icon and category", () => {
    const html = String(markerIcon(nodeShort(bagayam), "Infrastructure", "High").options.html);
    expect(html).toContain("<b>4 · Bagayam</b>");
    expect(html).toContain("Infrastructure · High");
    expect(html).toContain("<svg");
  });

  it("the alert list shows the full label with number and ward", () => {
    const a: Alert = {
      id: 1, node_id: "node-4", category: "Infrastructure", priority: "High", max_priority: "High", start_ts: "2018-01-07T12:00:00",
      last_ts: "2018-01-07T14:00:00", end_ts: null, status: "active", confidence: 0.8, explanation: "Infrastructure anomaly.",
    };
    render(<AlertList alerts={[a]} nodeNames={labelsById([bagayam])} />);
    expect(screen.getByText("Bagayam Booster (node-4 · Ward 4)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open Bagayam Booster \(node-4 · Ward 4\)/ })).toBeInTheDocument();
  });
});
