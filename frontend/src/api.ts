/**
 * The single module that owns every `fetch` in the app (§6).
 *
 * All paths are relative `/api/...`, with no base URL and no hostname: the Vite
 * dev server proxies `/api` to Flask on :5000, so the browser only ever makes a
 * same-origin request (§6). Hardcoding `http://localhost:5000` here would work
 * in dev only by accident and break the moment the app is served from anywhere
 * else — the proxy is the contract.
 */

import { ApiError, type Action, type ErrorCode, type MatchState } from "./types";

const HEADERS = { "Content-Type": "application/json" };

/**
 * Return the parsed body of a 2xx response, or throw the §5.4 error envelope.
 *
 * A non-2xx body that is missing or unparseable still has to produce something
 * a user can read, so it falls back to the status line rather than throwing a
 * `SyntaxError` from deep inside the fetch.
 */
async function parse(response: Response): Promise<MatchState> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok) {
    return body as MatchState;
  }

  const envelope = (body as { error?: { code?: string; message?: string } } | null)?.error;
  throw new ApiError(
    (envelope?.code as ErrorCode) ?? "unknown_error",
    envelope?.message ?? `Request failed with status ${response.status}.`,
    response.status,
  );
}

/** `POST /api/match` (§5.1). `seed` is omitted unless given, so play is random. */
export async function createMatch(
  playerFighter: string,
  opponentFighter: string,
  seed?: number,
): Promise<MatchState> {
  const body: Record<string, unknown> = {
    player_fighter: playerFighter,
    opponent_fighter: opponentFighter,
  };
  if (seed !== undefined) {
    body.seed = seed;
  }
  const response = await fetch("/api/match", {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify(body),
  });
  return parse(response);
}

/** `GET /api/match/<id>` (§5.3). Read-only; safe to call again after a reload. */
export async function getMatch(matchId: string): Promise<MatchState> {
  const response = await fetch(`/api/match/${matchId}`, { method: "GET" });
  return parse(response);
}

/** `POST /api/match/<id>/turn` (§5.2). The server picks the opponent's move. */
export async function submitTurn(matchId: string, action: Action): Promise<MatchState> {
  const response = await fetch(`/api/match/${matchId}/turn`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify({ action }),
  });
  return parse(response);
}
