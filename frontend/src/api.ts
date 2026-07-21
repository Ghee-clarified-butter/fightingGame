/**
 * The single module that owns every `fetch` in the app (§6).
 *
 * All paths are relative `/api/...`, with no base URL and no hostname: the Vite
 * dev server proxies `/api` to Flask on :5000, so the browser only ever makes a
 * same-origin request (§6). Hardcoding `http://localhost:5000` here would work
 * in dev only by accident and break the moment the app is served from anywhere
 * else — the proxy is the contract.
 */

import {
  ApiError,
  type Action,
  type Bracket,
  type Difficulty,
  type ErrorCode,
  type MatchState,
  type TournamentSummary,
} from "./types";

const HEADERS = { "Content-Type": "application/json" };

/**
 * Return the parsed body of a 2xx response, or throw the §5.4 error envelope.
 *
 * Generic over the success shape: a match returns a `MatchState`, a tournament
 * a `Bracket`, the list a `TournamentSummary[]` — all share one envelope on
 * failure. A non-2xx body that is missing or unparseable still has to produce
 * something a user can read, so it falls back to the status line rather than
 * throwing a `SyntaxError` from deep inside the fetch.
 */
async function parse<T>(response: Response): Promise<T> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok) {
    return body as T;
  }

  const envelope = (body as { error?: { code?: string; message?: string } } | null)?.error;
  throw new ApiError(
    (envelope?.code as ErrorCode) ?? "unknown_error",
    envelope?.message ?? `Request failed with status ${response.status}.`,
    response.status,
  );
}

/**
 * `POST /api/match` (§5.1, E4). `seed` is omitted unless given, so play is
 * random; `difficulty` is omitted unless given, so the server defaults it to
 * `"random"` and a Step 1 call stays byte-identical (E1).
 */
export async function createMatch(
  playerFighter: string,
  opponentFighter: string,
  seed?: number,
  difficulty?: Difficulty,
): Promise<MatchState> {
  const body: Record<string, unknown> = {
    player_fighter: playerFighter,
    opponent_fighter: opponentFighter,
  };
  if (seed !== undefined) {
    body.seed = seed;
  }
  if (difficulty !== undefined) {
    body.difficulty = difficulty;
  }
  const response = await fetch("/api/match", {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify(body),
  });
  return parse<MatchState>(response);
}

/** `GET /api/match/<id>` (§5.3). Read-only; safe to call again after a reload. */
export async function getMatch(matchId: string): Promise<MatchState> {
  const response = await fetch(`/api/match/${matchId}`, { method: "GET" });
  return parse<MatchState>(response);
}

/** `POST /api/match/<id>/turn` (§5.2). The server picks the opponent's move. */
export async function submitTurn(matchId: string, action: Action): Promise<MatchState> {
  const response = await fetch(`/api/match/${matchId}/turn`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ action }),
  });
  return parse<MatchState>(response);
}

/**
 * `POST /api/tournament` (E8). Creates the whole bracket and returns the E8.1
 * object. `seed` is required — the tournament is deterministic, so the server
 * rejects an absent one with `invalid_seed` (E7.3).
 */
export async function createTournament(
  name: string,
  roster: string[],
  difficulty: Difficulty,
  seed: number,
): Promise<Bracket> {
  const response = await fetch("/api/tournament", {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ name, roster, difficulty, seed }),
  });
  return parse<Bracket>(response);
}

/** `GET /api/tournament/<id>` (E8). Read-only; returns the E8.1 bracket. */
export async function getTournament(tournamentId: string): Promise<Bracket> {
  const response = await fetch(`/api/tournament/${tournamentId}`, { method: "GET" });
  return parse<Bracket>(response);
}

/**
 * `POST /api/tournament/<id>/advance` (E8). Plays the next ready match AI-vs-AI
 * and returns the updated bracket; one call advances exactly one match.
 */
export async function advanceTournament(tournamentId: string): Promise<Bracket> {
  const response = await fetch(`/api/tournament/${tournamentId}/advance`, {
    method: "POST",
    headers: HEADERS,
  });
  return parse<Bracket>(response);
}

/** `GET /api/tournaments` (E8). Lists every tournament, newest first. */
export async function listTournaments(): Promise<TournamentSummary[]> {
  const response = await fetch("/api/tournaments", { method: "GET" });
  return parse<TournamentSummary[]>(response);
}
