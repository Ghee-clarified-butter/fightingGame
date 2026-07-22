/**
 * The tournament standings table (E8.1, E9).
 *
 * Renders the derived `standings` rows exactly as the server sends them —
 * already sorted (wins desc → name → seed, B11) and already carrying each
 * entrant's `display` string, so the client neither sorts nor builds any prose.
 * Each row shows the entrant, its wins, its losses, and the round it was
 * eliminated in (`eliminated_in`), which is `null` for the champion and for any
 * entrant still in the running.
 */

import type { StandingsRow } from "../types";

/** How a row's `eliminated_in` is shown: the round it lost in, or a dash. */
function eliminatedLabel(eliminatedIn: number | null): string {
  return eliminatedIn === null ? "—" : `Round ${eliminatedIn}`;
}

export default function Standings({ standings }: { standings: StandingsRow[] }) {
  return (
    <section className="flex flex-col gap-2" data-testid="standings">
      <h3 className="text-sm font-semibold uppercase text-slate-400">Standings</h3>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs uppercase text-slate-500">
            <th className="px-2 py-1 font-semibold">Fighter</th>
            <th className="px-2 py-1 font-semibold">Wins</th>
            <th className="px-2 py-1 font-semibold">Losses</th>
            <th className="px-2 py-1 font-semibold">Eliminated</th>
          </tr>
        </thead>
        <tbody>
          {standings.map((row) => (
            <tr
              key={row.fighter.display}
              data-testid="standings-row"
              className="border-t border-slate-700 text-slate-200"
            >
              <td data-testid="standings-fighter" className="px-2 py-1">
                {row.fighter.display}
              </td>
              <td data-testid="standings-wins" className="px-2 py-1">
                {row.wins}
              </td>
              <td data-testid="standings-losses" className="px-2 py-1">
                {row.losses}
              </td>
              <td data-testid="standings-eliminated" className="px-2 py-1 text-slate-400">
                {eliminatedLabel(row.eliminated_in)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
