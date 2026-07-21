/**
 * The scrolling battle log (§7).
 *
 * Entries are rendered from `text` alone — the server prerenders every sentence
 * (§5.5), so this component composes no prose of its own. The list is oldest
 * first and scrolled to the bottom so the newest entry stays visible.
 */

import { useEffect, useRef } from "react";
import type { LogEntry } from "../types";

export default function BattleLog({ log }: { log: LogEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest entry in view as the log grows (§7). `scrollIntoView` is
  // absent under jsdom, so it is called only when the environment provides it.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [log.length]);

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-bold">Battle Log</h2>
      <ol
        aria-label="Battle Log"
        data-testid="battle-log"
        className="h-48 overflow-y-auto rounded bg-slate-800 p-2 text-sm"
      >
        {log.map((entry, index) => (
          <li
            // Entries are append-only and never reordered, so the index is a
            // stable identity; turn numbers repeat within a turn.
            key={index}
            data-testid="log-entry"
            className="border-b border-slate-700 py-1 last:border-b-0"
          >
            {entry.text}
          </li>
        ))}
        <div ref={endRef} />
      </ol>
    </section>
  );
}
