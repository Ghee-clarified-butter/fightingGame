import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ResultScreen from "./ResultScreen";

describe("ResultScreen", () => {
  it("renders a distinct message per terminal status", () => {
    const messages = (["player_won", "opponent_won", "draw"] as const).map((status) => {
      const { unmount } = render(<ResultScreen status={status} onNewMatch={() => {}} />);
      const text = screen.getByTestId("result-message").textContent ?? "";
      unmount();
      return text;
    });

    expect(messages.every((text) => text.length > 0)).toBe(true);
    expect(new Set(messages).size).toBe(3);
  });

  it("offers a new-match control that fires its callback", () => {
    const onNewMatch = vi.fn();
    render(<ResultScreen status="player_won" onNewMatch={onNewMatch} />);

    fireEvent.click(screen.getByRole("button", { name: /new match/i }));

    expect(onNewMatch).toHaveBeenCalledTimes(1);
  });

  it("renders nothing while the match is in progress", () => {
    render(<ResultScreen status="in_progress" onNewMatch={() => {}} />);

    expect(screen.queryByTestId("result-screen")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
