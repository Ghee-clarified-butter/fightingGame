/**
 * The wire types of the §5.5 match state object.
 *
 * These mirror what the server sends, field for field. They are deliberately
 * plain data: the client renders a `MatchState` and never derives rules from it
 * (§1, §6) — even `legal_actions` is consumed as data, not recomputed.
 */

/** The six move ids of §3, in the canonical order the UI lays them out. */
export const ACTIONS = [
  "strike",
  "ki_blast",
  "surge_beam",
  "charge",
  "guard",
  "ascend",
] as const;

export type Action = (typeof ACTIONS)[number];

export type Status = "in_progress" | "player_won" | "opponent_won" | "draw";

export type Actor = "player" | "opponent";

/** The three AI policies of E1; fixed at match creation. */
export type Difficulty = "random" | "heuristic" | "search";

export interface Fighter {
  id: string;
  name: string;
  hp: number;
  hp_max: number;
  ki: number;
  ki_max: number;
  atk: number;
  def: number;
  spd: number;
  /** Always false in a returned state (§5.5); no UI may key off it. */
  guarding: boolean;
  ascended: boolean;
  ascend_used: boolean;
  /** Consecutive non-attacking actions; AI bookkeeping only (E2.1). */
  passive_streak: number;
}

export interface LogEntry {
  turn: number;
  actor: Actor;
  action: Action;
  damage: number;
  target_hp: number;
  /** Prerendered by the server so the client builds no sentences (§5.5). */
  text: string;
}

export interface MatchState {
  match_id: string;
  status: Status;
  turn: number;
  /** The AI policy this match was created with (E1); never changes. */
  difficulty: Difficulty;
  player: Fighter;
  opponent: Fighter;
  /** Empty whenever `status` is not `in_progress` (§5.5). */
  legal_actions: Action[];
  log: LogEntry[];
}

/**
 * A tournament entrant, as rendered server-side (B11, E8.1).
 *
 * `display` is `"Kaito (2)"` — the fighter name plus its seed number — built by
 * the server so two entrants of the same fighter stay distinguishable and the
 * client assembles no strings of its own (consistent with §5.5's `text`).
 */
export interface Entrant {
  id: string;
  name: string;
  display: string;
}

/** The lifecycle of a whole tournament (E6.1, E7.4). */
export type TournamentStatus = "pending" | "in_progress" | "complete" | "stalled";

/** The lifecycle of a single bracket slot (E6.1, E7.1, E7.4). */
export type BracketMatchStatus =
  | "pending"
  | "ready"
  | "complete"
  | "bye"
  | "drawn_out";

/** One bracket slot in the E8.1 object. A side is `null` when a bye or undetermined. */
export interface BracketMatch {
  match_id: string;
  slot: number;
  status: BracketMatchStatus;
  fighter_a: Entrant | null;
  fighter_b: Entrant | null;
  winner: Entrant | null;
  /** Turns the decisive attempt took; `null` for a bye or an unplayed match. */
  turns: number | null;
}

/** One round of the bracket, its matches ordered by slot (E8.1). */
export interface BracketRound {
  round: number;
  matches: BracketMatch[];
}

/**
 * One standings row (E8.1), derived server-side and never stored.
 *
 * Keyed by seed, not fighter id, so duplicate entrants never merge (E7.2).
 * `eliminated_in` is the round the entrant lost in, or `null` for the champion.
 */
export interface StandingsRow {
  fighter: Entrant;
  wins: number;
  losses: number;
  eliminated_in: number | null;
}

/** The full E8.1 bracket object returned by the tournament endpoints. */
export interface Bracket {
  tournament_id: string;
  name: string;
  difficulty: Difficulty;
  seed: number;
  size: number;
  status: TournamentStatus;
  champion: Entrant | null;
  rounds: BracketRound[];
  standings: StandingsRow[];
}

/** A row in `GET /api/tournaments`, newest first (E8, E8.1). */
export interface TournamentSummary {
  id: string;
  name: string;
  status: TournamentStatus;
  champion: Entrant | null;
  /** ISO-8601, so the client can show it without parsing a database dialect. */
  created_at: string;
}

/** The error codes of §5.4, widened with Step 2's Part A and Part B codes (E4, E8). */
export type ErrorCode =
  | "unknown_fighter"
  | "unknown_action"
  | "invalid_seed"
  | "insufficient_ki"
  | "already_ascended"
  | "match_over"
  | "match_not_found"
  | "unknown_difficulty"
  | "invalid_name"
  | "invalid_roster"
  | "tournament_not_found"
  | "tournament_complete"
  | "no_ready_match";

/** The §5.4 envelope, as thrown by the API module. */
export class ApiError extends Error {
  readonly code: ErrorCode | "unknown_error";
  readonly status: number;

  constructor(code: ErrorCode | "unknown_error", message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}
