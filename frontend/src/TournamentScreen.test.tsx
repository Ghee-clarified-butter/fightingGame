import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TournamentScreen from "./TournamentScreen";
import { ApiError, type Bracket, type Entrant, type TournamentSummary } from "./types";

vi.mock("./api", () => ({
  createTournament: vi.fn(),
  getTournament: vi.fn(),
  advanceTournament: vi.fn(),
  listTournaments: vi.fn(),
}));

const api = await import("./api");
const createTournament = vi.mocked(api.createTournament);
const advanceTournament = vi.mocked(api.advanceTournament);
const listTournaments = vi.mocked(api.listTournaments);

const KAITO: Entrant = { id: "kaito", name: "Kaito", display: "Kaito (1)" };
const VEGA: Entrant = { id: "vega", name: "Vega", display: "Vega (2)" };

/** A minimal two-entrant, single-match bracket in the given lifecycle state. */
function bracket(overrides: Partial<Bracket> = {}): Bracket {
  return {
    tournament_id: "t1",
    name: "Spring Cup",
    difficulty: "heuristic",
    seed: 99,
    size: 2,
    status: "in_progress",
    champion: null,
    rounds: [
      {
        round: 1,
        matches: [
          {
            match_id: "m0",
            slot: 0,
            status: "ready",
            fighter_a: { ...KAITO },
            fighter_b: { ...VEGA },
            winner: null,
            turns: null,
          },
        ],
      },
    ],
    standings: [
      { fighter: { ...KAITO }, wins: 0, losses: 0, eliminated_in: null },
      { fighter: { ...VEGA }, wins: 0, losses: 0, eliminated_in: null },
    ],
    ...overrides,
  };
}

function completeBracket(): Bracket {
  const done = bracket({ status: "complete", champion: { ...KAITO } });
  done.rounds[0].matches[0] = {
    ...done.rounds[0].matches[0],
    status: "complete",
    winner: { ...KAITO },
    turns: 14,
  };
  return done;
}

function summary(overrides: Partial<TournamentSummary> = {}): TournamentSummary {
  return {
    id: "t1",
    name: "Spring Cup",
    status: "in_progress",
    champion: null,
    created_at: "2026-07-21T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listTournaments.mockResolvedValue([]);
});

/** Empty the roster one entry at a time, re-querying so indices stay fresh. */
function clearRoster() {
  let remaining = screen.queryAllByRole("button", { name: /remove entrant/i });
  while (remaining.length > 0) {
    act(() => remaining[0].click());
    remaining = screen.queryAllByRole("button", { name: /remove entrant/i });
  }
}

describe("TournamentScreen", () => {
  it("posts the roster, difficulty and seed from the create form", async () => {
    createTournament.mockResolvedValue(bracket());

    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());

    // Craft a known roster: clear the default four, then add one of each.
    clearRoster();
    act(() => screen.getByTestId("add-kaito").click());
    act(() => screen.getByTestId("add-vega").click());

    fireEvent.change(screen.getByTestId("tournament-name"), { target: { value: "My Cup" } });
    fireEvent.change(screen.getByTestId("difficulty-select"), { target: { value: "search" } });
    fireEvent.change(screen.getByTestId("tournament-seed"), { target: { value: "123" } });

    await act(async () => {
      screen.getByTestId("create-tournament").click();
    });

    expect(createTournament).toHaveBeenCalledWith("My Cup", ["kaito", "vega"], "search", 123);
    expect(screen.getByTestId("bracket")).toBeInTheDocument();
  });

  it("disables Create until the roster has at least two entrants", async () => {
    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());

    clearRoster();
    // Zero entrants: rejected client-side before any request.
    expect(screen.getByTestId("create-tournament")).toBeDisabled();

    act(() => screen.getByTestId("add-kaito").click());
    expect(screen.getByTestId("create-tournament")).toBeDisabled();

    act(() => screen.getByTestId("add-vega").click());
    expect(screen.getByTestId("create-tournament")).toBeEnabled();
  });

  it("advances one match per click and re-renders the returned bracket", async () => {
    createTournament.mockResolvedValue(bracket());
    advanceTournament.mockResolvedValue(completeBracket());

    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());
    await act(async () => {
      screen.getByTestId("create-tournament").click();
    });

    await act(async () => {
      screen.getByTestId("advance").click();
    });

    expect(advanceTournament).toHaveBeenCalledTimes(1);
    expect(advanceTournament).toHaveBeenCalledWith("t1");
    // The updated bracket is rendered: the champion is now called out.
    expect(screen.getByTestId("champion").textContent).toContain("Kaito (1)");
  });

  it("advances only once when a second click lands while the first is in flight", async () => {
    createTournament.mockResolvedValue(bracket());
    let release: (value: Bracket) => void = () => {};
    advanceTournament.mockReturnValue(
      new Promise<Bracket>((resolve) => {
        release = resolve;
      }),
    );

    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());
    await act(async () => {
      screen.getByTestId("create-tournament").click();
    });

    const advance = screen.getByTestId("advance");
    act(() => {
      advance.click();
    });
    // In flight: the button is disabled, so a second click cannot fire.
    expect(advance).toBeDisabled();
    act(() => {
      advance.click();
    });

    await act(async () => {
      release(completeBracket());
    });
    expect(advanceTournament).toHaveBeenCalledTimes(1);
  });

  it("disables Advance once the tournament is complete", async () => {
    createTournament.mockResolvedValue(completeBracket());

    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());
    await act(async () => {
      screen.getByTestId("create-tournament").click();
    });

    expect(screen.getByTestId("advance")).toBeDisabled();
  });

  it("lists past tournaments newest first, as the server ordered them", async () => {
    listTournaments.mockResolvedValue([
      summary({ id: "t2", name: "Newer", status: "complete", champion: { ...VEGA } }),
      summary({ id: "t1", name: "Older" }),
    ]);

    render(<TournamentScreen />);

    const list = await screen.findByTestId("tournament-list");
    const rows = within(list).getAllByTestId("tournament-summary");
    expect(rows).toHaveLength(2);
    // The API already sorts newest first (E8); the client renders that order.
    expect(rows[0].textContent).toContain("Newer");
    expect(rows[0].textContent).toContain("Vega (2)");
    expect(rows[1].textContent).toContain("Older");
  });

  it("opens a past tournament when its row is clicked", async () => {
    listTournaments.mockResolvedValue([summary()]);
    const getTournament = vi.mocked(api.getTournament);
    getTournament.mockResolvedValue(bracket());

    render(<TournamentScreen />);
    const row = await screen.findByTestId("tournament-summary");

    await act(async () => {
      row.click();
    });

    expect(getTournament).toHaveBeenCalledWith("t1");
    expect(screen.getByTestId("bracket")).toBeInTheDocument();
  });

  it("shows an API error without discarding the bracket on screen", async () => {
    createTournament.mockResolvedValue(bracket());
    advanceTournament.mockRejectedValueOnce(
      new ApiError("no_ready_match", "No match is ready to play.", 409),
    );

    render(<TournamentScreen />);
    await waitFor(() => expect(listTournaments).toHaveBeenCalled());
    await act(async () => {
      screen.getByTestId("create-tournament").click();
    });

    await act(async () => {
      screen.getByTestId("advance").click();
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("No match is ready to play.");
    // The bracket the user was looking at is still there.
    expect(screen.getByTestId("bracket")).toBeInTheDocument();
  });
});
