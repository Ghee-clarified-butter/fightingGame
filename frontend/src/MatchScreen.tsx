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
import { ApiError, type Action, type MatchState } from "./types";
import StatBars from "./components/StatBars";
import MoveButtons from "./components/MoveButtons";
import BattleLog from "./components/BattleLog";
import ResultScreen from "./components/ResultScreen";

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

  // `busy` state alone cannot gate a second click in the same tick: React
  // batches the update, so both handlers would still read `busy === false`.
  // A ref flips synchronously, which is what "only one turn in flight" needs.
  const inFlight = useRef(false);

  const startMatch = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      setMatch(await createMatch(PLAYER_FIGHTER, OPPONENT_FIGHTER));
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

  if (match === null) {
    return (
      <div className="flex flex-col gap-2">
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
