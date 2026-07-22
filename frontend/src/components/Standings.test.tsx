import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import Standings from "./Standings";
import type { StandingsRow } from "../types";

/**
 * A finished four-entrant tournament's standings, already sorted by the server
 * (wins desc → name → seed, B11). Two of the entrants share the fighter id
 * `kaito` and must stay separate rows with distinct `display` strings (E7.2).
 */
const STANDINGS: StandingsRow[] = [
  { fighter: { id: "kaito", name: "Kaito", display: "Kaito (1)" }, wins: 2, losses: 0, eliminated_in: null },
  { fighter: { id: "vega", name: "Vega", display: "Vega (2)" }, wins: 1, losses: 1, eliminated_in: 2 },
  { fighter: { id: "kaito", name: "Kaito", display: "Kaito (3)" }, wins: 0, losses: 1, eliminated_in: 1 },
  { fighter: { id: "vega", name: "Vega", display: "Vega (4)" }, wins: 0, losses: 1, eliminated_in: 1 },
];

function rowCells(row: HTMLElement) {
  return {
    fighter: within(row).getByTestId("standings-fighter").textContent,
    wins: within(row).getByTestId("standings-wins").textContent,
    losses: within(row).getByTestId("standings-losses").textContent,
    eliminated: within(row).getByTestId("standings-eliminated").textContent,
  };
}

describe("Standings", () => {
  it("renders one row per entrant in the server's order", () => {
    render(<Standings standings={STANDINGS} />);

    const rows = screen.getAllByTestId("standings-row");
    expect(rows).toHaveLength(4);
    expect(rows.map((row) => within(row).getByTestId("standings-fighter").textContent)).toEqual([
      "Kaito (1)",
      "Vega (2)",
      "Kaito (3)",
      "Vega (4)",
    ]);
  });

  it("shows wins, losses and the elimination round for each row", () => {
    render(<Standings standings={STANDINGS} />);

    const vega = screen
      .getByText("Vega (2)")
      .closest("[data-testid='standings-row']") as HTMLElement;
    expect(rowCells(vega)).toEqual({
      fighter: "Vega (2)",
      wins: "1",
      losses: "1",
      eliminated: "Round 2",
    });
  });

  it("shows a dash for an entrant that was never eliminated (the champion)", () => {
    render(<Standings standings={STANDINGS} />);

    const champion = screen
      .getByText("Kaito (1)")
      .closest("[data-testid='standings-row']") as HTMLElement;
    expect(within(champion).getByTestId("standings-eliminated").textContent).toBe("—");
  });

  it("keeps two same-fighter entrants as distinct rows", () => {
    render(<Standings standings={STANDINGS} />);

    // Both Kaito entrants have their own row, never merged into one.
    expect(screen.getByText("Kaito (1)")).toBeInTheDocument();
    expect(screen.getByText("Kaito (3)")).toBeInTheDocument();
    expect(screen.getAllByTestId("standings-row")).toHaveLength(4);
  });

  it("renders an empty standings table without crashing", () => {
    render(<Standings standings={[]} />);

    expect(screen.queryAllByTestId("standings-row")).toHaveLength(0);
    expect(screen.getByTestId("standings")).toBeInTheDocument();
  });
});
