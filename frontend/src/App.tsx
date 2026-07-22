/**
 * The app shell: a plain state toggle between the two views (E9).
 *
 * A single-elimination tournament and a one-off arena match are the only two
 * screens, so a router dependency would be overkill — a `useState` toggle is
 * exactly what E9 sanctions. Each view owns all of its own state, so switching
 * is a straight unmount/remount with nothing to thread between them.
 */

import { useState } from "react";
import MatchScreen from "./MatchScreen";
import TournamentScreen from "./TournamentScreen";

type View = "arena" | "tournament";

const TABS: { view: View; label: string }[] = [
  { view: "arena", label: "Arena" },
  { view: "tournament", label: "Tournament" },
];

export default function App() {
  const [view, setView] = useState<View>("arena");

  return (
    <main className="min-h-screen bg-slate-900 p-8 text-slate-100">
      <h1 className="mb-6 text-3xl font-bold">Base Arena</h1>

      <nav className="mb-6 flex gap-2" aria-label="Views">
        {TABS.map((tab) => (
          <button
            key={tab.view}
            type="button"
            data-testid={`tab-${tab.view}`}
            aria-current={view === tab.view ? "page" : undefined}
            onClick={() => setView(tab.view)}
            className={
              "rounded px-4 py-2 text-sm font-semibold " +
              (view === tab.view
                ? "bg-indigo-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700")
            }
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {view === "arena" ? <MatchScreen /> : <TournamentScreen />}
    </main>
  );
}
