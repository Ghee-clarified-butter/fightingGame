/**
 * The AI difficulty selector for the match screen (E5).
 *
 * Difficulty is fixed at match creation (E1), so this is a plain controlled
 * `<select>` that the caller disables once a match is in progress. It offers
 * exactly the three E1 policies and never picks a move itself — it only reports
 * which policy the next match should be created with.
 */

import { type Difficulty } from "../types";

/** The three E1 policies, in the order they are offered. `random` is the default. */
const DIFFICULTIES: Difficulty[] = ["random", "heuristic", "search"];

/** Human-readable labels; presentation only, the wire value stays the id (E1). */
const LABELS: Record<Difficulty, string> = {
  random: "Random",
  heuristic: "Heuristic",
  search: "Search",
};

interface DifficultySelectProps {
  value: Difficulty;
  disabled: boolean;
  onChange: (difficulty: Difficulty) => void;
}

export default function DifficultySelect({ value, disabled, onChange }: DifficultySelectProps) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-sm font-semibold uppercase text-slate-400">Difficulty</span>
      <select
        data-testid="difficulty-select"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as Difficulty)}
        className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-40"
      >
        {DIFFICULTIES.map((difficulty) => (
          <option key={difficulty} value={difficulty}>
            {LABELS[difficulty]}
          </option>
        ))}
      </select>
    </label>
  );
}

export { DIFFICULTIES, LABELS };
