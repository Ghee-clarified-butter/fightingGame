/**
 * The single-elimination bracket view (E9).
 *
 * Renders the E8.1 bracket object exactly as the server sends it: rounds in
 * order, every match in each round, winners highlighted, byes labelled, and the
 * champion called out only once the tournament is `complete`. Like the rest of
 * the client it derives nothing — every entrant carries its own server-built
 * `display` string (B11), so two entrants of the same fighter stay distinct
 * ("Kaito (1)" vs "Kaito (2)") without the client assembling any prose.
 */

import type { Bracket as BracketData, BracketMatch, Entrant } from "../types";

/**
 * Is this entrant the match's winner? A `null` side is never a winner.
 *
 * Two entrants can share a fighter id (E7.2), so id alone can't tell the sides
 * apart, and the server sends `winner` as its own JSON object so reference
 * identity never holds. The `display` string carries the seed ("Kaito (2)", B11)
 * and so is unique per entrant within a bracket — the right key to match on.
 */
function isWinner(match: BracketMatch, entrant: Entrant | null): boolean {
  return (
    entrant !== null &&
    match.winner !== null &&
    match.winner.display === entrant.display
  );
}

/** One side of a match: an entrant, a bye placeholder, or an undetermined slot. */
function EntrantSide({
  entrant,
  won,
  bye,
}: {
  entrant: Entrant | null;
  won: boolean;
  bye: boolean;
}) {
  if (entrant === null) {
    return (
      <div
        data-testid="entrant-side"
        className="px-2 py-1 text-sm italic text-slate-500"
      >
        {bye ? "Bye" : "—"}
      </div>
    );
  }

  return (
    <div
      data-testid="entrant-side"
      data-winner={won ? "true" : "false"}
      className={
        "px-2 py-1 text-sm " +
        (won ? "font-bold text-amber-300" : "text-slate-200")
      }
    >
      {won && (
        <span data-testid="winner-mark" aria-label="winner" className="mr-1">
          ✓
        </span>
      )}
      {entrant.display}
    </div>
  );
}

/** A single bracket slot (E8.1). Byes are labelled and show no turn count. */
function MatchCard({ match }: { match: BracketMatch }) {
  const bye = match.status === "bye";

  return (
    <div
      data-testid="bracket-match"
      className="flex flex-col divide-y divide-slate-700 rounded border border-slate-700 bg-slate-800"
    >
      <EntrantSide
        entrant={match.fighter_a}
        won={isWinner(match, match.fighter_a)}
        bye={bye}
      />
      <EntrantSide
        entrant={match.fighter_b}
        won={isWinner(match, match.fighter_b)}
        bye={bye}
      />
      {bye ? (
        <div data-testid="bye-label" className="px-2 py-1 text-xs uppercase text-slate-500">
          Bye
        </div>
      ) : (
        match.turns !== null && (
          <div data-testid="match-turns" className="px-2 py-1 text-xs text-slate-400">
            {match.turns} turns
          </div>
        )
      )}
    </div>
  );
}

export default function Bracket({ bracket }: { bracket: BracketData }) {
  return (
    <section className="flex flex-col gap-4" data-testid="bracket">
      {bracket.status === "complete" && bracket.champion !== null && (
        <p
          data-testid="champion"
          className="rounded bg-amber-500 px-4 py-2 text-center text-lg font-bold text-slate-900"
        >
          Champion: {bracket.champion.display}
        </p>
      )}
      <div className="flex gap-4 overflow-x-auto">
        {bracket.rounds.map((round) => (
          <div
            key={round.round}
            data-testid="bracket-round"
            className="flex min-w-[10rem] flex-col gap-3"
          >
            <h3 className="text-sm font-semibold uppercase text-slate-400">
              Round {round.round}
            </h3>
            {round.matches.map((match) => (
              <MatchCard key={match.match_id} match={match} />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
