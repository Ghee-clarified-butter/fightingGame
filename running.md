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

### If port 5000 is already taken

Port 5000 is a popular default, so this is common. Flask exits immediately with *"Address already
in use"*, or on Windows *"An attempt was made to access a socket in a way forbidden by its access
permissions"*. Override it — the Vite proxy target follows the same variable:

    BACKEND_PORT=5055 ./script/server        # FRONTEND_PORT overrides :5173 the same way

Two things make this collision confusing enough to be worth spelling out:

- **The app still loads, and then reports `404`.** Vite happily proxies `/api` to whatever is on
  port 5000. If that is an HTTP service, the browser shows a running UI whose first request fails.
  On the development machine here it was a `registry:2` Docker container inside WSL — WSL2 mirrors
  its listening sockets onto Windows `localhost`, so Windows `netstat` showed *nothing* on 5000
  while connections to it succeeded. A `404` in this app is worth checking against the backend
  before assuming it is an application bug.
- **A busy `:5173` used to be silent.** Vite's default is to shift to the next free port, so you
  could end up reading a stale tab on `:5174`. `./script/server` now passes `--strictPort`, so a
  taken frontend port is a hard failure rather than a quiet redirection.

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

That HTTP-level pass could not cover a human in a real browser, so one followed (2026-07-21). The
app was opened at `http://localhost:5173` and rendered a live match: Kaito 100/100 HP and 30/100 ki
against Vega 130/130 HP, HP and ki bars showing both a filled width and the numbers, all six moves
listed with their ki costs, and an empty battle log at turn 0.

**Surge Beam and Ascend rendered disabled** — both cost 40 ki against a 30 ki pool — while Strike,
Ki Blast, Charge and Guard stayed enabled. That is the server's `legal_actions` driving the UI: the
client applies no rule of its own, it renders what the backend says is allowed (§6, §7).

The equivalent flow end to end (mount → play → result screen → new match, with no reload) is
asserted in `frontend/src/MatchScreen.test.tsx`, and CORS is ruled out at the HTTP level above.

## Extension features
- (Step 2) Choose AI difficulty on the match screen.
- (Step 2) Tournament bracket; results persist across server restarts.
