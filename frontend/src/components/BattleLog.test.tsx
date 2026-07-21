import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import BattleLog from "./BattleLog";
import type { LogEntry } from "../types";

const ENTRIES: LogEntry[] = [
  {
    turn: 1,
    actor: "player",
    action: "strike",
    damage: 9,
    target_hp: 121,
    text: "Kaito lands a Strike for 9. Vega: 121 HP.",
  },
  {
    turn: 1,
    actor: "opponent",
    action: "charge",
    damage: 0,
    target_hp: 100,
    text: "Vega charges up. Ki: 55.",
  },
  {
    turn: 2,
    actor: "player",
    action: "ki_blast",
    damage: 16,
    target_hp: 105,
    text: "Kaito fires a Ki Blast for 16. Vega: 105 HP.",
  },
];

function renderedTexts(): string[] {
  return screen.getAllByTestId("log-entry").map((li) => li.textContent ?? "");
}

describe("BattleLog", () => {
  it("renders every entry oldest-first", () => {
    render(<BattleLog log={ENTRIES} />);

    expect(renderedTexts()).toEqual(ENTRIES.map((entry) => entry.text));
  });

  it("builds no sentences of its own", () => {
    render(<BattleLog log={ENTRIES} />);

    // Nothing beyond the heading and the verbatim `text` values may appear:
    // no actor labels, no damage numbers the server did not already render.
    const list = screen.getByTestId("battle-log");
    expect(list.textContent).toBe(ENTRIES.map((entry) => entry.text).join(""));
  });

  it("renders an empty log without crashing", () => {
    render(<BattleLog log={[]} />);

    expect(screen.queryAllByTestId("log-entry")).toHaveLength(0);
    expect(screen.getByTestId("battle-log").textContent).toBe("");
  });

  it("is a scrolling region so the newest entry stays reachable", () => {
    render(<BattleLog log={ENTRIES} />);

    expect(screen.getByTestId("battle-log").className).toContain("overflow-y-auto");
  });
});
