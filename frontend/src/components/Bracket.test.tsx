import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import Bracket from "./Bracket";
import type { Bracket as BracketData, Entrant } from "../types";

const KAITO_1: Entrant = { id: "kaito", name: "Kaito", display: "Kaito (1)" };
const KAITO_2: Entrant = { id: "kaito", name: "Kaito", display: "Kaito (2)" };
const VEGA: Entrant = { id: "vega", name: "Vega", display: "Vega (3)" };

/**
 * A four-entrant, size-4 bracket mid-play: round 1 fully resolved (one bye),
 * the final not yet played. Every side is a *fresh* object, so `winner` is never
 * reference-identical to `fighter_a`/`fighter_b` — exactly what JSON parsing of a
 * real server payload gives us.
 */
function inProgressBracket(): BracketData {
  return {
    tournament_id: "t1",
    name: "Spring Cup",
    difficulty: "heuristic",
    seed: 99,
    size: 4,
    status: "in_progress",
    champion: null,
    rounds: [
      {
        round: 1,
        matches: [
          {
            match_id: "m0",
            slot: 0,
            status: "complete",
            fighter_a: { ...KAITO_1 },
            fighter_b: { ...VEGA },
            winner: { ...KAITO_1 },
            turns: 12,
          },
          {
            match_id: "m1",
            slot: 1,
            status: "bye",
            fighter_a: { ...KAITO_2 },
            fighter_b: null,
            winner: { ...KAITO_2 },
            turns: null,
          },
        ],
      },
      {
        round: 2,
        matches: [
          {
            match_id: "m2",
            slot: 0,
            status: "ready",
            fighter_a: { ...KAITO_1 },
            fighter_b: { ...KAITO_2 },
            winner: null,
            turns: null,
          },
        ],
      },
    ],
    standings: [],
  };
}

function completeBracket(): BracketData {
  const bracket = inProgressBracket();
  bracket.status = "complete";
  bracket.champion = { ...KAITO_1 };
  const final = bracket.rounds[1].matches[0];
  final.status = "complete";
  final.winner = { ...KAITO_1 };
  final.turns = 20;
  return bracket;
}

describe("Bracket", () => {
  it("renders every round in order with each of its matches", () => {
    render(<Bracket bracket={inProgressBracket()} />);

    const rounds = screen.getAllByTestId("bracket-round");
    expect(rounds).toHaveLength(2);
    expect(within(rounds[0]).getByRole("heading").textContent).toBe("Round 1");
    expect(within(rounds[1]).getByRole("heading").textContent).toBe("Round 2");

    expect(within(rounds[0]).getAllByTestId("bracket-match")).toHaveLength(2);
    expect(within(rounds[1]).getAllByTestId("bracket-match")).toHaveLength(1);
  });

  it("marks the winner of a played match even though winner is a separate object", () => {
    render(<Bracket bracket={inProgressBracket()} />);

    // The played round-1 match: Kaito (1) beat Vega (3). Scope to round 1's first
    // match — "Kaito (1)" also appears as a finalist in round 2.
    const round1 = screen.getAllByTestId("bracket-round")[0];
    const match = within(round1).getAllByTestId("bracket-match")[0];
    const winnerSide = within(match)
      .getByText("Kaito (1)")
      .closest("[data-testid='entrant-side']") as HTMLElement;
    const loserSide = within(match)
      .getByText("Vega (3)")
      .closest("[data-testid='entrant-side']") as HTMLElement;

    expect(winnerSide).toHaveAttribute("data-winner", "true");
    expect(within(winnerSide).getByTestId("winner-mark")).toBeInTheDocument();
    expect(loserSide).toHaveAttribute("data-winner", "false");
  });

  it("labels a bye and shows no turn count for it", () => {
    render(<Bracket bracket={inProgressBracket()} />);

    const byeMatch = screen.getByTestId("bye-label").closest(
      "[data-testid='bracket-match']",
    ) as HTMLElement;
    // "Bye" appears twice in the card: the empty side placeholder and the label.
    expect(within(byeMatch).getAllByText("Bye").length).toBeGreaterThanOrEqual(1);
    expect(within(byeMatch).queryByTestId("match-turns")).toBeNull();
    // A bye's advancing entrant is still shown on the seeded side.
    expect(within(byeMatch).getByText("Kaito (2)")).toBeInTheDocument();
  });

  it("shows the turn count for a played, non-bye match", () => {
    render(<Bracket bracket={inProgressBracket()} />);

    const round1 = screen.getAllByTestId("bracket-round")[0];
    const match = within(round1).getAllByTestId("bracket-match")[0];
    expect(within(match).getByTestId("match-turns").textContent).toContain("12");
  });

  it("does not call out a champion while the tournament is in progress", () => {
    render(<Bracket bracket={inProgressBracket()} />);
    expect(screen.queryByTestId("champion")).toBeNull();
  });

  it("calls out the champion once the tournament is complete", () => {
    render(<Bracket bracket={completeBracket()} />);

    const champion = screen.getByTestId("champion");
    expect(champion.textContent).toContain("Kaito (1)");
  });

  it("keeps two same-fighter entrants distinct by their display labels", () => {
    render(<Bracket bracket={inProgressBracket()} />);

    // Both Kaito entrants appear; the final pits Kaito (1) against Kaito (2),
    // and neither is merged into a single label.
    expect(screen.getAllByText("Kaito (1)").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Kaito (2)").length).toBeGreaterThanOrEqual(1);

    const final = screen.getAllByTestId("bracket-round")[1];
    expect(within(final).getByText("Kaito (1)")).toBeInTheDocument();
    expect(within(final).getByText("Kaito (2)")).toBeInTheDocument();
  });
});
