import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NotifyStatus } from "../types";
import { AlertPushStatus } from "./AlertPushStatus";

const status = (over: Partial<NotifyStatus> = {}): NotifyStatus => ({
  mode: "dry_run",
  sent: 2,
  suppressed: 1,
  failed: 0,
  last_send_utc: null,
  budget_remaining: 78,
  ...over,
});

function mockFetch(body: NotifyStatus | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => (body ? { ok: true, json: async () => body } : { ok: false, status: 503, statusText: "x", json: async () => ({}) })),
  );
}

describe("AlertPushStatus", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says dry run with the counts when nothing is sent", async () => {
    mockFetch(status());
    render(<AlertPushStatus />);
    expect(await screen.findByText("Alerts: dry run")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 sent, 1 held back, 0 failed");
    expect(screen.getByRole("status")).not.toHaveTextContent("left in budget");
  });

  it("says WhatsApp on with the remaining budget in Twilio mode", async () => {
    mockFetch(status({ mode: "twilio" }));
    render(<AlertPushStatus />);
    expect(await screen.findByText("Alerts: WhatsApp on")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("78 left in budget");
  });

  it("shows an error state when the status cannot be loaded", async () => {
    mockFetch(null);
    render(<AlertPushStatus />);
    expect(await screen.findByText("Alerts: status unavailable")).toBeInTheDocument();
  });
});
