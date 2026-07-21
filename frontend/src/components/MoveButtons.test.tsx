import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MoveButtons from "./MoveButtons";
import { ACTIONS, type Action } from "../types";

const ALL_NAMES = [
  "Strike",
  "Ki Blast",
  "Surge Beam",
  "Charge",
  "Guard",
  "Ascend",
];

function button(action: Action): HTMLButtonElement {
  const el = document.querySelector<HTMLButtonElement>(`button[data-action="${action}"]`);
  if (el === null) {
    throw new Error(`no button for ${action}`);
  }
  return el;
}

describe("MoveButtons", () => {
  it("renders all six moves whatever is legal", () => {
    render(<MoveButtons legalActions={["strike"]} busy={false} onSelect={() => {}} />);

    expect(screen.getAllByRole("button")).toHaveLength(6);
    for (const name of ALL_NAMES) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("enables exactly the actions present in legal_actions", () => {
    render(
      <MoveButtons
        legalActions={["strike", "charge", "guard"]}
        busy={false}
        onSelect={() => {}}
      />,
    );

    expect(button("strike")).toBeEnabled();
    expect(button("charge")).toBeEnabled();
    expect(button("guard")).toBeEnabled();
    expect(button("ki_blast")).toBeDisabled();
    expect(button("surge_beam")).toBeDisabled();
    expect(button("ascend")).toBeDisabled();
  });

  it("shows each move's ki cost", () => {
    render(<MoveButtons legalActions={[...ACTIONS]} busy={false} onSelect={() => {}} />);

    const costs = ACTIONS.map((action) => button(action).textContent ?? "");
    expect(costs).toEqual([
      "Strike0 ki",
      "Ki Blast15 ki",
      "Surge Beam40 ki",
      "Charge0 ki",
      "Guard0 ki",
      "Ascend40 ki",
    ]);
  });

  it("disables every button while busy, even legal ones", () => {
    render(<MoveButtons legalActions={[...ACTIONS]} busy onSelect={() => {}} />);

    for (const action of ACTIONS) {
      expect(button(action)).toBeDisabled();
    }
  });

  it("fires onSelect with the action id", () => {
    const onSelect = vi.fn();
    render(<MoveButtons legalActions={["ki_blast"]} busy={false} onSelect={onSelect} />);

    fireEvent.click(button("ki_blast"));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("ki_blast");
  });

  it("is entirely unclickable with an empty legal_actions", () => {
    const onSelect = vi.fn();
    render(<MoveButtons legalActions={[]} busy={false} onSelect={onSelect} />);

    for (const action of ACTIONS) {
      expect(button(action)).toBeDisabled();
      fireEvent.click(button(action));
    }

    expect(onSelect).not.toHaveBeenCalled();
  });
});
