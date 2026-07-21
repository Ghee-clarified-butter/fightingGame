import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

// `App` mounts the match screen, which creates a match on mount; the API module
// is the app's only network boundary (§6), so stubbing it keeps this a pure
// render test.
vi.mock("./api", () => ({
  createMatch: vi.fn(() => new Promise(() => {})),
  getMatch: vi.fn(),
  submitTurn: vi.fn(),
}));

describe("App", () => {
  it("renders the arena title", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Base Arena" }),
    ).toBeInTheDocument();
  });

  it("mounts the match screen", () => {
    render(<App />);
    expect(screen.getByTestId("loading")).toBeInTheDocument();
  });
});
