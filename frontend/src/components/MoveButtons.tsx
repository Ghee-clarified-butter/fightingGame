/**
 * The six move buttons (§7).
 *
 * All six are always rendered so the layout never shifts; a button is enabled
 * iff its action appears in `legal_actions`. That list is server-computed data
 * (§5.5) — this component reimplements no rule, not even "surge_beam needs 40
 * ki". `busy` disables everything while a turn request is in flight so a
 * double-click cannot submit two turns.
 */

import { ACTIONS, type Action } from "../types";

/** Display name and ki cost per move (§3). Presentation only — costs are shown, never enforced. */
const MOVE_INFO: Record<Action, { name: string; cost: number }> = {
  strike: { name: "Strike", cost: 0 },
  ki_blast: { name: "Ki Blast", cost: 15 },
  surge_beam: { name: "Surge Beam", cost: 40 },
  charge: { name: "Charge", cost: 0 },
  guard: { name: "Guard", cost: 0 },
  ascend: { name: "Ascend", cost: 40 },
};

interface MoveButtonsProps {
  legalActions: Action[];
  busy: boolean;
  onSelect: (action: Action) => void;
}

export default function MoveButtons({ legalActions, busy, onSelect }: MoveButtonsProps) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {ACTIONS.map((action) => {
        const { name, cost } = MOVE_INFO[action];
        const disabled = busy || !legalActions.includes(action);
        return (
          <button
            key={action}
            type="button"
            data-action={action}
            disabled={disabled}
            onClick={() => onSelect(action)}
            className="flex flex-col items-start rounded border border-slate-600 bg-slate-800 px-3 py-2 text-left enabled:hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="font-semibold">{name}</span>
            <span className="text-xs text-slate-400 tabular-nums">{cost} ki</span>
          </button>
        );
      })}
    </div>
  );
}
