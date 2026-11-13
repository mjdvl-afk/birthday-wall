# CLAUDE.md: Birthday video wall

## What this is
A local tool that turns a folder of "happy birthday" videos into a synced video wall in the browser and an exported MP4. Whisper (faster-whisper, run locally on the CPU) transcribes each clip and finds where "happy birthday" starts. All clips are then lined up on that moment so everyone says it together. The human-facing guide is `README.md`; keep it to one page.

## Helping someone set it up
Work through these in order and check each one before moving on:
1. **macOS.** The code assumes a Mac (see "Portability" below). If the user is on Windows or Linux, warn them first and offer the fixes listed there.
2. **ffmpeg + ffprobe** on PATH: `brew install ffmpeg`. The test-clip tool uses `hevc_videotoolbox`, which the Homebrew build includes.
3. **Python 3.10+** in a venv at `.venv/`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. `wall.py` automatically re-runs itself under `.venv/bin/python` if that exists, so plain `python3 wall.py ...` works.
4. Ask for the birthday person's name. Set `RECIPIENT` at the top of `wall.py` **and** of `tools/make_test_clips.py`.
5. Smoke test: `.venv/bin/python tools/make_test_clips.py` (24 synthetic clips plus `sample_videos/_ground_truth.json`), then `python3 wall.py build sample_videos`. Compare the detected moments with the ground truth; within about ±0.1s is expected. "Jess (no phrase)" should come back as missing on purpose. Then start the preview with `python3 wall.py serve` (port 8000; `.claude/launch.json` is set up for this).
6. Real videos go in `videos/`. Run `python3 wall.py build` (switching source folders wipes `build/clips`), then `serve`, then `export`.

## Commands
- `python3 wall.py build [folder]`: transcodes each video to `build/clips/<slug>/full.mp4` (up to 1080p, H.264, 30fps) plus a square 480px `tile.mp4`. The tile starts with `TILE_PAD` seconds of frozen first frame so every tile can start at the same instant. It also transcribes, writes `build/cache.json` and `build/manifest.{json,js}`, makes posters, and copies `web/` into `build/`. It's incremental: a clip is skipped when the file's size and mtime haven't changed.
- `python3 wall.py serve [port]`: a ThreadingHTTPServer on 127.0.0.1 that serves `build/`, with live files from `web/`, byte-range support (Safari needs it), and three POST endpoints: `/api/sync`, `/api/name`, `/api/transcript`. `/manifest.js` is regenerated on every request.
- `python3 wall.py export`: renders a title card, then the wall (xstack + amix + loudnorm), then each full message with a blurred background and a name tag, and concatenates them into `export/<slug(TITLE)>.mp4`.

## Files
- `wall.py`: everything on the Python side. The tunable settings are at the top (RECIPIENT, TITLE, LEAD, WALL_AFTER, WHISPER_MODEL, export size, GAP, MAX_TILE_ASPECT, COLORS).
- `web/index.html`, `web/app.js`, `web/style.css`: the wall UI (plain JS, no build step, reads `window.WALL` from `manifest.js`). The backtick key toggles debug mode.
- `web/names.html`: a page for editing names in bulk.
- `tools/make_test_clips.py`: makes synthetic test clips with macOS `say` and Pillow.
- User state, all keyed by the **original file name** and kept across rebuilds:
  - `names.json`: file → display name; blank means no name tag. Build adds a blank entry for each tile.
  - `sync_overrides.json`: file → moment in seconds, set by hand.
  - `transcripts.json`: file → corrected transcript. `""` means show no transcript.
  - `joins.json`: a list of file lists to play back to back as one tile. Files named `Name_1`, `Name_2`, ... are joined automatically.
- Generated, gitignored: `build/`, `export/`, `.venv/`. `videos/` and `sample_videos/` are gitignored too.

## How the moment is found
`find_happy_birthday()` normalizes the Whisper words. If it sees "happy" followed by "birth…" or "bday", it uses the start of "birthday" minus 0.33s, because Whisper's start time for "happy" drifts early after a pause. A word starting with "happybirth" counts directly. If it only hears "birthday", it subtracts 0.4s and marks the result "guess". If it hears nothing, the moment is "missing" and the user sets it by hand in the UI.

## Portability (Mac-specific bits)
- `FONT` in both scripts points to `/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf`. On another OS, point it to any .ttf file.
- `avconvert` (macOS only) is used for iPhone HDR clips when it's available. Otherwise the code falls back to ffmpeg's tone conversion, which looks a bit washed out.
- `tools/make_test_clips.py` needs macOS `say` and its voices. On Linux, swap in `espeak-ng` or skip the test clips.

## Conventions
- Never modify or delete the user's source videos. They're only read.
- Don't commit real videos or the filled-in JSON state files to a public repo. They contain guests' names and what they said.
- Keep changes small and in the existing style (a single file, stdlib plus ffmpeg, no frameworks).
