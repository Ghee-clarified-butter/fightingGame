/**
 * The win/lose/draw screen (§7).
 *
 * Rendered only once `status` leaves `in_progress`; while the match is live the
 * component renders nothing at all, so the caller can mount it unconditionally.
 * The status is server-authoritative data (§5.5) — nothing here decides who won.
 */

import type { Status } from "../types";

/** One headline per terminal status (§5.5). `in_progress` has no screen. */
const MESSAGES: Record<Exclude<Status, "in_progress">, string> = {
  player_won: "You win!",
  opponent_won: "You lose.",
  draw: "Draw.",
};

interface ResultScreenProps {
  status: Status;
  onNewMatch: () => void;
}

export default function ResultScreen({ status, onNewMatch }: ResultScreenProps) {
  if (status === "in_progress") return null;

  return (
    <section
      data-testid="result-screen"
      className="flex flex-col items-center gap-3 rounded bg-slate-800 p-6"
    >
      <p data-testid="result-message" className="text-2xl font-bold">
        {MESSAGES[status]}
      </p>
      <button
        type="button"
        onClick={onNewMatch}
        className="rounded bg-amber-500 px-4 py-2 font-semibold text-slate-900 hover:bg-amber-400"
      >
        New Match
      </button>
    </section>
  );
}
