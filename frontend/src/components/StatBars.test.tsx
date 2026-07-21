import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatBars from "./StatBars";
import type { Fighter } from "../types";

function kaito(overrides: Partial<Fighter> = {}): Fighter {
  return {
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
    ...overrides,
  };
}

function vega(overrides: Partial<Fighter> = {}): Fighter {
  return {
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
    ...overrides,
  };
}

describe("StatBars", () => {
  it("shows hp and ki numerically and by width", () => {
    render(<StatBars fighter={kaito({ hp: 78, ki: 15 })} />);

    expect(screen.getByText("78 / 100")).toBeInTheDocument();
    expect(screen.getByText("15 / 100")).toBeInTheDocument();
    expect(screen.getByTestId("hp-fill")).toHaveStyle({ width: "78%" });
    expect(screen.getByTestId("ki-fill")).toHaveStyle({ width: "15%" });
  });

  it("renders a 0% hp bar without collapsing the track", () => {
    render(<StatBars fighter={kaito({ hp: 0 })} />);

    expect(screen.getByText("0 / 100")).toBeInTheDocument();
    expect(screen.getByTestId("hp-fill")).toHaveStyle({ width: "0%" });
    // The track itself survives, so the layout does not jump on a KO.
    expect(screen.getByRole("progressbar", { name: "HP" })).toBeInTheDocument();
  });

  it("scales width against the fighter's own max, not an absolute", () => {
    render(<StatBars fighter={vega({ hp: 65 })} />);

    expect(screen.getByText("65 / 130")).toBeInTheDocument();
    expect(screen.getByTestId("hp-fill")).toHaveStyle({ width: "50%" });
  });

  it("names the fighter it belongs to", () => {
    render(<StatBars fighter={vega()} />);

    expect(screen.getByRole("heading", { name: "Vega" })).toBeInTheDocument();
  });
});
