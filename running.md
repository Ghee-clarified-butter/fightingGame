# Running Fighting Game

A turn-based 1v1 arena. A Flask backend owns every rule; the React client only draws what the
server sends back.

## Prerequisites
- Python 3.12 or newer (developed and tested on 3.13.5)
- Node 20 or newer (developed and tested on 22.19.0)
- Git Bash if you are on Windows — the `script/*` entry points are shell scripts

## Setup
    git clone <your-repo-url> && cd fightingGame
    ./script/setup

Creates `.venv`, installs `backend/requirements.txt` into it, and installs the frontend packages.
Safe to re-run.

## Run
    ./script/server        # backend :5000, frontend :5173
    # open http://localhost:5173

Ctrl+C stops both. The client only ever requests relative `/api/...` paths; Vite proxies them to
Flask, so the browser makes same-origin requests and no CORS configuration exists anywhere in the
backend (specs/base.md §6).

If something else on your machine already owns port 5000 (Flask then exits with *"An attempt was
made to access a socket in a way forbidden by its access permissions"* or *"Address already in
use"*), override the port — the Vite proxy target follows the same variable:

    BACKEND_PORT=5055 ./script/server        # FRONTEND_PORT overrides :5173 the same way

## Test
    ./script/test          # pytest (backend) + vitest (frontend)
    ./script/lint          # flake8 + eslint

## How to play

You are **Kaito**; the server plays **Vega**. Each turn you pick one of six moves, the server picks
the opponent's, and both resolve in speed order — so a turn can hurt you before your own move lands.

| Move | Ki | What it does |
|---|---|---|
| Strike | 0 | Light attack. Always available, even at 0 ki. |
| Ki Blast | 15 | Medium attack. |
| Surge Beam | 40 | Heavy attack. |
| Charge | 0 | Skip attacking to regain 25 ki (30 while ascended). |
| Guard | 0 | Halve the damage you take this turn and regain 8 ki. |
| Ascend | 40 | Once per match: +25% damage and +5 speed for the rest of the fight. |

Ki only comes back from Charge and Guard, so the whole game is deciding when to spend a turn not
attacking. Moves you cannot afford are greyed out — the button state comes from the server's
`legal_actions`, the client never decides legality itself.

First fighter to 0 HP loses. If both are still standing after 100 turns, the winner is whoever has
the larger share of their own max HP; exactly equal shares are a draw. When the match ends a result
screen appears with a **New match** button, which starts a fresh fight without reloading the page.

## Verified end to end

2026-07-21, on this repo at Phase 4: `./script/server` was started and a full match was played
against the running pair, every request going to a relative `/api/...` path on the frontend origin
(`:5173`) and reaching Flask through the Vite proxy.

- Vite served the app on `:5173`; `POST /api/match` returned 201 through the proxy.
- A seeded Kaito-vs-Vega match ran 13 turns to a terminal status (`opponent_won`), the final state
  reporting `legal_actions: []` — the result-screen state.
- Proxied responses carry **no `Access-Control-*` headers**, confirming the requests are same-origin
  and that no CORS handling is needed (§6, §8).
- A turn submitted on the finished match came back `409 match_over` in the §5.4 envelope; starting a
  new match left the finished one untouched.
- Port 5000 was occupied by an unrelated service on the verification machine, so the backend ran on
  `BACKEND_PORT=5055`; the proxy followed it, which is what that override exists for.

The one thing this did not cover is a human clicking through a real browser and reading its console.
The equivalent behaviour is asserted in `frontend/src/MatchScreen.test.tsx` (mount → play → result
screen → new match, with no reload), and CORS is ruled out at the HTTP level above.

## Extension features
- (Step 2) Choose AI difficulty on the match screen.
- (Step 2) Tournament bracket; results persist across server restarts.
