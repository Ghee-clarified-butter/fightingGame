# Running Fighting Game

> Placeholder — filled in once Step 1 / Stage 4 (Build) produces a runnable game.

## Prerequisites
- Python 3.12 or newer (developed and tested on 3.13.5)
- Node 20 or newer (developed and tested on 22.19.0)
- Git Bash if you are on Windows — the `script/*` entry points are shell scripts

## Setup
    git clone <your-repo-url> && cd fightingGame
    ./script/setup

## Run
    ./script/server        # backend :5000, frontend :5173
    # open http://localhost:5173

## Test
    ./script/test

## Extension features
- (Step 2) Choose AI difficulty on the match screen.
- (Step 2) Tournament bracket; results persist across server restarts.
