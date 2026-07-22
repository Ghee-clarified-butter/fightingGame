import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import App from "./App";

// `App` mounts a view, and each view is a stateful shell over the API module —
// the app's only network boundary (§6) — so stubbing it keeps this a pure render
// test. `createMatch`/`listTournaments` never resolve, so no view settles and no
// assertion races an in-flight fetch.
vi.mock("./api", () => ({
  createMatch: vi.fn(() => new Promise(() => {})),
  getMatch: vi.fn(),
  submitTurn: vi.fn(),
  createTournament: vi.fn(),
  getTournament: vi.fn(),
  advanceTournament: vi.fn(),
  listTournaments: vi.fn(() => new Promise(() => {})),
}));

describe("App", () => {
  it("renders the arena title", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Base Arena" }),
    ).toBeInTheDocument();
  });

  it("mounts the match screen by default", () => {
    render(<App />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(screen.queryByTestId("tournament-form")).toBeNull();
  });

  it("toggles to the tournament view and back to the arena", () => {
    render(<App />);

    act(() => {
      screen.getByTestId("tab-tournament").click();
    });
    expect(screen.getByTestId("tournament-form")).toBeInTheDocument();
    expect(screen.queryByTestId("loading")).toBeNull();

    act(() => {
      screen.getByTestId("tab-arena").click();
    });
    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(screen.queryByTestId("tournament-form")).toBeNull();
  });
});
