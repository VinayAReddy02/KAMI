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
    expect(screen.getByRole("status")).toHaveClass("push-dry"); // colour class, plus the icon and the text
    expect(screen.getByRole("status").querySelector(".push-icon")).not.toBeNull();
  });

  it("says Telegram on when the bot is used", async () => {
    mockFetch(status({ mode: "telegram" }));
    render(<AlertPushStatus />);
    expect(await screen.findByText("Alerts: Telegram on")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveClass("push-on");
    expect(screen.getByRole("status")).toHaveTextContent("2 sent, 1 held back, 0 failed");
  });

  it("shows an error state when the status cannot be loaded", async () => {
    mockFetch(null);
    render(<AlertPushStatus />);
    expect(await screen.findByText("Alerts: status unavailable")).toBeInTheDocument();
  });
});
