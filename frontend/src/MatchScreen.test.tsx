import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MatchScreen from "./MatchScreen";
import { ApiError, type Action, type MatchState } from "./types";

vi.mock("./api", () => ({
  createMatch: vi.fn(),
  getMatch: vi.fn(),
  submitTurn: vi.fn(),
}));

const api = await import("./api");
const createMatch = vi.mocked(api.createMatch);
const submitTurn = vi.mocked(api.submitTurn);

function state(overrides: Partial<MatchState> = {}): MatchState {
  return {
    match_id: "m1",
    status: "in_progress",
    turn: 0,
    difficulty: "random",
    player: {
      id: "kaito",
      name: "Kaito",
      hp: 100,
      hp_max: 100,
      ki: 30,
      ki_max: 100,
      atk: 22,
      def: 8,
      spd: 14,
      guarding: false,
      ascended: false,
      ascend_used: false,
      passive_streak: 0,
    },
    opponent: {
      id: "vega",
      name: "Vega",
      hp: 130,
      hp_max: 130,
      ki: 30,
      ki_max: 100,
      atk: 16,
      def: 14,
      spd: 9,
      guarding: false,
      ascended: false,
      ascend_used: false,
      passive_streak: 0,
    },
    legal_actions: ["strike", "ki_blast", "charge", "guard"],
    log: [],
    ...overrides,
  };
}

/** Click the button for `action` outside RTL's auto-`act`, so no state flushes between clicks. */
function rawClick(action: Action) {
  const button = document.querySelector<HTMLButtonElement>(`button[data-action="${action}"]`);
  if (button === null) throw new Error(`no button for ${action}`);
  button.click();
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MatchScreen", () => {
  it("creates a match on mount and renders both fighters", async () => {
    createMatch.mockResolvedValue(state());

    render(<MatchScreen />);

    expect(await screen.findByRole("heading", { name: "Kaito" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Vega" })).toBeInTheDocument();
    expect(createMatch).toHaveBeenCalledTimes(1);
    // Difficulty defaults to random (E1); seed is left for the server to draw.
    expect(createMatch).toHaveBeenCalledWith("kaito", "vega", undefined, "random");
  });

  it("submits the clicked move and re-renders from the response", async () => {
    createMatch.mockResolvedValue(state());
    submitTurn.mockResolvedValue(
      state({
        turn: 1,
        opponent: { ...state().opponent, hp: 112 },
        log: [
          {
            turn: 1,
            actor: "player",
            action: "strike",
            damage: 18,
            target_hp: 112,
            text: "Kaito strikes Vega for 18 damage.",
          },
        ],
      }),
    );

    render(<MatchScreen />);
    const strike = await screen.findByRole("button", { name: /strike/i });

    await act(async () => {
      strike.click();
    });

    expect(submitTurn).toHaveBeenCalledWith("m1", "strike");
    expect(screen.getByText("Kaito strikes Vega for 18 damage.")).toBeInTheDocument();
    expect(screen.getByText("112 / 130")).toBeInTheDocument();
  });

  it("submits only one turn when a second click lands while the first is in flight", async () => {
    createMatch.mockResolvedValue(state());
    let release: (value: MatchState) => void = () => {};
    submitTurn.mockReturnValue(
      new Promise<MatchState>((resolve) => {
        release = resolve;
      }),
    );

    render(<MatchScreen />);
    await screen.findByRole("button", { name: /strike/i });

    await act(async () => {
      rawClick("strike");
      rawClick("strike");
      release(state({ turn: 1 }));
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
  });

  it("disables every move button while a turn is in flight", async () => {
    createMatch.mockResolvedValue(state());
    let release: (value: MatchState) => void = () => {};
    submitTurn.mockReturnValue(
      new Promise<MatchState>((resolve) => {
        release = resolve;
      }),
    );

    render(<MatchScreen />);
    const strike = await screen.findByRole("button", { name: /strike/i });

    act(() => {
      strike.click();
    });

    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }

    await act(async () => {
      release(state({ turn: 1 }));
    });
    expect(screen.getByRole("button", { name: /strike/i })).toBeEnabled();
  });

  it("swaps in the result screen on a terminal status and hides the move buttons", async () => {
    createMatch.mockResolvedValue(
      state({ status: "player_won", legal_actions: [], turn: 12 }),
    );

    render(<MatchScreen />);

    expect(await screen.findByTestId("result-screen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /strike/i })).toBeNull();
  });

  it("creates a fresh match from the result screen without a reload", async () => {
    createMatch
      .mockResolvedValueOnce(state({ match_id: "m1", status: "opponent_won", legal_actions: [] }))
      .mockResolvedValueOnce(state({ match_id: "m2" }));

    render(<MatchScreen />);
    const newMatch = await screen.findByRole("button", { name: /new match/i });

    await act(async () => {
      newMatch.click();
    });

    expect(createMatch).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("result-screen")).toBeNull();

    submitTurn.mockResolvedValue(state({ match_id: "m2", turn: 1 }));
    await act(async () => {
      rawClick("strike");
    });
    expect(submitTurn).toHaveBeenCalledWith("m2", "strike");
  });

  it("surfaces an API error as a readable message and keeps playing", async () => {
    createMatch.mockResolvedValue(state());
    submitTurn.mockRejectedValueOnce(
      new ApiError("insufficient_ki", "Not enough ki for surge_beam.", 400),
    );

    render(<MatchScreen />);
    const strike = await screen.findByRole("button", { name: /strike/i });

    await act(async () => {
      strike.click();
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Not enough ki for surge_beam.");
    // The UI is not wedged: the state survived and the buttons are live again.
    expect(screen.getByText("100 / 100")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /strike/i })).toBeEnabled();

    submitTurn.mockResolvedValue(state({ turn: 1 }));
    await act(async () => {
      rawClick("strike");
    });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(submitTurn).toHaveBeenCalledTimes(2);
  });

  it("offers a difficulty selector defaulting to random with all three policies", async () => {
    createMatch.mockResolvedValue(state());

    render(<MatchScreen />);
    await screen.findByRole("button", { name: /strike/i });

    const selector = screen.getByTestId("difficulty-select") as HTMLSelectElement;
    expect(selector.value).toBe("random");
    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.value)).toEqual(["random", "heuristic", "search"]);
  });

  it("disables the selector and shows the difficulty while a match is in progress", async () => {
    createMatch.mockResolvedValue(state({ difficulty: "search" }));

    render(<MatchScreen />);
    await screen.findByRole("button", { name: /strike/i });

    expect(screen.getByTestId("difficulty-select")).toBeDisabled();
    expect(screen.getByTestId("current-difficulty")).toHaveTextContent("Search");
  });

  it("sends the chosen difficulty when a new match is started", async () => {
    // First match ends immediately, which re-enables the selector; the second
    // creation must carry whatever the user then picked.
    createMatch
      .mockResolvedValueOnce(state({ status: "player_won", legal_actions: [] }))
      .mockResolvedValueOnce(state({ match_id: "m2", difficulty: "search" }));

    render(<MatchScreen />);
    await screen.findByTestId("result-screen");

    const selector = screen.getByTestId("difficulty-select") as HTMLSelectElement;
    expect(selector).toBeEnabled();
    fireEvent.change(selector, { target: { value: "search" } });

    await act(async () => {
      screen.getByRole("button", { name: /new match/i }).click();
    });

    expect(createMatch).toHaveBeenCalledTimes(2);
    expect(createMatch).toHaveBeenLastCalledWith("kaito", "vega", undefined, "search");
  });
});
