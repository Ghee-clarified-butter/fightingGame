/**
 * The match screen: the one stateful component in the app (§7).
 *
 * It holds a single `MatchState` and replaces it wholesale with whatever the
 * server returns. Nothing here computes damage or legality (§1, §6) — a move
 * click is a request, and the response is the new truth. `busy` covers the
 * whole request so a double-click cannot submit two turns (§7), and an API
 * error becomes a readable line without discarding the state the user is
 * looking at.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createMatch, submitTurn } from "./api";
import { ApiError, type Action, type Difficulty, type MatchState } from "./types";
import StatBars from "./components/StatBars";
import MoveButtons from "./components/MoveButtons";
import BattleLog from "./components/BattleLog";
import ResultScreen from "./components/ResultScreen";
import DifficultySelect, { LABELS as DIFFICULTY_LABELS } from "./components/DifficultySelect";

/** The §2.1 starters, in the fixed matchup of step 1. */
const PLAYER_FIGHTER = "kaito";
const OPPONENT_FIGHTER = "vega";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not reach the server. Check that the backend is running.";
}

export default function MatchScreen() {
  const [match, setMatch] = useState<MatchState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The difficulty for the *next* match. It is fixed at creation (E1), so the
  // selector is disabled while a match is live and this only changes between
  // matches.
  const [difficulty, setDifficulty] = useState<Difficulty>("random");

  // `busy` state alone cannot gate a second click in the same tick: React
  // batches the update, so both handlers would still read `busy === false`.
  // A ref flips synchronously, which is what "only one turn in flight" needs.
  const inFlight = useRef(false);

  // `startMatch` is created once (empty deps) so mounting fires it exactly one
  // time; it must therefore read the *current* difficulty rather than closing
  // over a stale one, hence a ref that tracks the state.
  const difficultyRef = useRef(difficulty);
  difficultyRef.current = difficulty;

  const startMatch = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      setMatch(
        await createMatch(PLAYER_FIGHTER, OPPONENT_FIGHTER, undefined, difficultyRef.current),
      );
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void startMatch();
  }, [startMatch]);

  const handleSelect = useCallback(
    async (action: Action) => {
      // The click can only come from an enabled button, but the guard is on the
      // handler rather than the button so an in-flight turn is refused even if
      // the re-render has not landed yet.
      if (inFlight.current || match === null) return;
      inFlight.current = true;
      setBusy(true);
      setError(null);
      try {
        setMatch(await submitTurn(match.match_id, action));
      } catch (caught) {
        // The state is left as-is: a rejected turn changes nothing server-side
        // (§5.4), so the screen the user sees is still correct.
        setError(messageFor(caught));
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [match],
  );

  // Difficulty is chosen at creation (E1), so the selector locks the moment a
  // match is live and reopens once it resolves. While `match` is still loading
  // (`null`) the request is already in flight, so `busy` keeps it locked too.
  const matchInProgress = match !== null && match.status === "in_progress";
  const selectorDisabled = busy || matchInProgress;

  if (match === null) {
    return (
      <div className="flex flex-col gap-2">
        <DifficultySelect
          value={difficulty}
          disabled={selectorDisabled}
          onChange={setDifficulty}
        />
        <p data-testid="loading">Starting match…</p>
        {error !== null && (
          <p data-testid="error" role="alert" className="text-rose-400">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <DifficultySelect
          value={matchInProgress ? match.difficulty : difficulty}
          disabled={selectorDisabled}
          onChange={setDifficulty}
        />
        {matchInProgress && (
          <p data-testid="current-difficulty" className="text-sm text-slate-400">
            Fighting the <span className="font-semibold">{DIFFICULTY_LABELS[match.difficulty]}</span>{" "}
            AI
          </p>
        )}
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <StatBars fighter={match.player} />
        <StatBars fighter={match.opponent} />
      </div>

      {match.status === "in_progress" ? (
        <MoveButtons legalActions={match.legal_actions} busy={busy} onSelect={handleSelect} />
      ) : (
        <ResultScreen status={match.status} onNewMatch={() => void startMatch()} />
      )}

      {error !== null && (
        <p data-testid="error" role="alert" className="text-rose-400">
          {error}
        </p>
      )}

      <BattleLog log={match.log} />
    </div>
  );
}
