import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DifficultySelect from "./DifficultySelect";

function select(): HTMLSelectElement {
  return screen.getByTestId("difficulty-select") as HTMLSelectElement;
}

describe("DifficultySelect", () => {
  it("offers exactly the three E1 policies", () => {
    render(<DifficultySelect value="random" disabled={false} onChange={() => {}} />);

    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.value)).toEqual(["random", "heuristic", "search"]);
    expect(options.map((option) => option.textContent)).toEqual([
      "Random",
      "Heuristic",
      "Search",
    ]);
  });

  it("shows the controlled value, defaulting to random when passed random", () => {
    render(<DifficultySelect value="random" disabled={false} onChange={() => {}} />);
    expect(select().value).toBe("random");
  });

  it("reflects whatever value it is given", () => {
    render(<DifficultySelect value="search" disabled={false} onChange={() => {}} />);
    expect(select().value).toBe("search");
  });

  it("reports a change through onChange with the picked policy", () => {
    const onChange = vi.fn();
    render(<DifficultySelect value="random" disabled={false} onChange={onChange} />);

    fireEvent.change(select(), { target: { value: "heuristic" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("heuristic");
  });

  it("is disabled when told to be", () => {
    render(<DifficultySelect value="random" disabled onChange={() => {}} />);
    expect(select()).toBeDisabled();
  });
});
