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
  player: Fighter;
  opponent: Fighter;
  /** Empty whenever `status` is not `in_progress` (§5.5). */
  legal_actions: Action[];
  log: LogEntry[];
}

/** The error codes of §5.4. */
export type ErrorCode =
  | "unknown_fighter"
  | "unknown_action"
  | "invalid_seed"
  | "insufficient_ki"
  | "already_ascended"
  | "match_over"
  | "match_not_found";

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
