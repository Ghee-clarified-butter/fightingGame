/**
 * HP and ki bars for one fighter (§7).
 *
 * Both values are shown numerically *and* as a width, because a bar alone can
 * not tell 78/100 from 101/130 — and the two starters have different maxima on
 * purpose (§2.1), so widths are always a fraction of that fighter's own max.
 */

import type { Fighter } from "../types";

/** Clamped so a malformed payload can never blow the bar past its track. */
function percent(current: number, max: number): number {
  if (max <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (current / max) * 100));
}

interface BarProps {
  label: string;
  current: number;
  max: number;
  fillClass: string;
}

function Bar({ label, current, max, fillClass }: BarProps) {
  const width = percent(current, max);
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 text-xs font-semibold uppercase text-slate-400">{label}</span>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={current}
        aria-valuemin={0}
        aria-valuemax={max}
        className="h-3 flex-1 overflow-hidden rounded bg-slate-700"
      >
        {/* The fill is a separate element so a 0% width leaves the track intact. */}
        <div data-testid={`${label.toLowerCase()}-fill`} className={`h-full ${fillClass}`} style={{ width: `${width}%` }} />
      </div>
      <span className="w-20 text-right text-sm tabular-nums">
        {current} / {max}
      </span>
    </div>
  );
}

export default function StatBars({ fighter }: { fighter: Fighter }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-bold">{fighter.name}</h2>
      <Bar label="HP" current={fighter.hp} max={fighter.hp_max} fillClass="bg-emerald-500" />
      <Bar label="KI" current={fighter.ki} max={fighter.ki_max} fillClass="bg-sky-500" />
    </section>
  );
}
