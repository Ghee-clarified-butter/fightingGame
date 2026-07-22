/**
 * The tournament screen (E9): create a bracket, advance it match by match, and
 * see the past tournaments that prove persistence across a restart.
 *
 * Like {@link MatchScreen} it is a thin stateful shell over the API module (§6):
 * it never computes a result, a seeding or a standing — it posts a roster and
 * renders whatever E8.1 object the server sends back. `busy`/`inFlight` gate the
 * whole request so Advance can only ever play one match per click (E9), and an
 * API error becomes a readable line without discarding the bracket on screen.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  advanceTournament,
  createTournament,
  getTournament,
  listTournaments,
} from "./api";
import { ApiError, type Bracket, type Difficulty, type TournamentSummary } from "./types";
import BracketView from "./components/Bracket";
import Standings from "./components/Standings";
import DifficultySelect from "./components/DifficultySelect";

/**
 * The fighters a roster can be built from. The base game ships two (§2.1); the
 * client mirrors the registry that seeds the server's `Fighter` table (E6.1)
 * rather than fetching it, exactly as {@link MatchScreen} hardcodes its matchup.
 */
const AVAILABLE_FIGHTERS: { id: string; name: string }[] = [
  { id: "kaito", name: "Kaito" },
  { id: "vega", name: "Vega" },
];

/** A tournament needs at least two entrants and is capped at sixteen (E7.1/E7.2). */
const MIN_ROSTER = 2;
const MAX_ROSTER = 16;

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not reach the server. Check that the backend is running.";
}

/** Is the tournament finished, so that Advance has nothing left to play? */
function isOver(bracket: Bracket): boolean {
  return bracket.status === "complete" || bracket.status === "stalled";
}

export default function TournamentScreen() {
  const [name, setName] = useState("Spring Cup");
  const [roster, setRoster] = useState<string[]>(["kaito", "vega", "kaito", "vega"]);
  const [difficulty, setDifficulty] = useState<Difficulty>("heuristic");
  const [seed, setSeed] = useState(99);

  const [bracket, setBracket] = useState<Bracket | null>(null);
  const [summaries, setSummaries] = useState<TournamentSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A ref flips synchronously, so a second click in the same tick is refused
  // even before React re-renders the disabled button (as in MatchScreen).
  const inFlight = useRef(false);

  const refreshList = useCallback(async () => {
    try {
      setSummaries(await listTournaments());
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const addFighter = useCallback((id: string) => {
    setRoster((current) =>
      current.length >= MAX_ROSTER ? current : [...current, id],
    );
  }, []);

  const removeAt = useCallback((index: number) => {
    setRoster((current) => current.filter((_, i) => i !== index));
  }, []);

  const handleCreate = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const created = await createTournament(name, roster, difficulty, seed);
      setBracket(created);
      await refreshList();
    } catch (caught) {
      // The bracket already on screen (if any) survives a failed creation.
      setError(messageFor(caught));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [name, roster, difficulty, seed, refreshList]);

  const handleAdvance = useCallback(async () => {
    if (inFlight.current || bracket === null || isOver(bracket)) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const updated = await advanceTournament(bracket.tournament_id);
      setBracket(updated);
      await refreshList();
    } catch (caught) {
      // A rejected advance changes nothing server-side, so the displayed
      // bracket is still correct and is left in place.
      setError(messageFor(caught));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [bracket, refreshList]);

  const handleOpen = useCallback(async (id: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      setBracket(await getTournament(id));
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, []);

  const rosterValid = roster.length >= MIN_ROSTER && roster.length <= MAX_ROSTER;
  const advanceDisabled = busy || bracket === null || isOver(bracket);

  return (
    <div className="flex flex-col gap-6">
      <section
        data-testid="tournament-form"
        className="flex flex-col gap-3 rounded border border-slate-700 bg-slate-800 p-4"
      >
        <h2 className="text-lg font-semibold">New tournament</h2>

        <label className="flex items-center gap-2">
          <span className="w-20 text-sm font-semibold uppercase text-slate-400">Name</span>
          <input
            data-testid="tournament-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="flex-1 rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm"
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <span className="w-20 text-sm font-semibold uppercase text-slate-400">Roster</span>
          {AVAILABLE_FIGHTERS.map((fighter) => (
            <button
              key={fighter.id}
              type="button"
              data-testid={`add-${fighter.id}`}
              onClick={() => addFighter(fighter.id)}
              disabled={roster.length >= MAX_ROSTER}
              className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-sm hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              + {fighter.name}
            </button>
          ))}
        </div>

        <ul data-testid="roster" className="flex flex-wrap gap-2">
          {roster.map((id, index) => (
            <li
              key={`${id}-${index}`}
              data-testid="roster-entry"
              className="flex items-center gap-1 rounded bg-slate-700 px-2 py-1 text-sm"
            >
              <span>
                {index + 1}. {id}
              </span>
              <button
                type="button"
                aria-label={`remove entrant ${index + 1}`}
                onClick={() => removeAt(index)}
                className="text-slate-400 hover:text-rose-400"
              >
                ✕
              </button>
            </li>
          ))}
          {roster.length === 0 && (
            <li className="text-sm italic text-slate-500">No entrants yet</li>
          )}
        </ul>

        <div className="flex flex-wrap items-center gap-4">
          <DifficultySelect value={difficulty} disabled={busy} onChange={setDifficulty} />
          <label className="flex items-center gap-2">
            <span className="text-sm font-semibold uppercase text-slate-400">Seed</span>
            <input
              type="number"
              data-testid="tournament-seed"
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
              className="w-28 rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm"
            />
          </label>
        </div>

        <button
          type="button"
          data-testid="create-tournament"
          onClick={() => void handleCreate()}
          disabled={busy || !rosterValid}
          className="self-start rounded bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Create tournament
        </button>
      </section>

      {error !== null && (
        <p data-testid="error" role="alert" className="text-rose-400">
          {error}
        </p>
      )}

      {bracket !== null && (
        <section className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">
              {bracket.name}{" "}
              <span className="text-sm font-normal text-slate-400">({bracket.status})</span>
            </h2>
            <button
              type="button"
              data-testid="advance"
              onClick={() => void handleAdvance()}
              disabled={advanceDisabled}
              className="rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Advance
            </button>
          </div>
          <BracketView bracket={bracket} />
          <Standings standings={bracket.standings} />
        </section>
      )}

      <section data-testid="tournament-list" className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Past tournaments</h2>
        {summaries.length === 0 ? (
          <p className="text-sm italic text-slate-500">No tournaments yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {summaries.map((summary) => (
              <li key={summary.id}>
                <button
                  type="button"
                  data-testid="tournament-summary"
                  onClick={() => void handleOpen(summary.id)}
                  disabled={busy}
                  className="flex w-full flex-wrap items-center gap-2 rounded border border-slate-700 bg-slate-800 px-3 py-2 text-left text-sm hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="font-semibold">{summary.name}</span>
                  <span className="text-slate-400">{summary.status}</span>
                  {summary.champion !== null && (
                    <span className="text-amber-300">🏆 {summary.champion.display}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
