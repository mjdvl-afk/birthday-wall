# Birthday video wall

Collect short "happy birthday" videos from friends and family. This tool shows them all as one grid that plays in sync, so everyone says "happy birthday" at the same moment. It can also export the whole thing as one video file. Speech recognition (Whisper, running on your own computer) finds the moment in each clip, and nothing is uploaded anywhere.

**Needs:** a Mac, Python 3.10+, and ffmpeg (`brew install ffmpeg`). If you're working with Claude Code, open this folder and say *"set this up for me"*. `CLAUDE.md` tells it everything.

## Setup (once)
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Open `wall.py` and set `RECIPIENT = "..."` near the top. The other settings (lead-in seconds, how long the wall runs in the export) are right below it.

## Use it
1. Drop videos into `videos/` (or any folder: `python3 wall.py build ~/Desktop/vids`). Any format is fine. Tiles go in file-name order. Originals are only read, never changed.
2. `python3 wall.py build` converts the videos and finds "happy birthday" in each. The first run downloads the speech model (about 500 MB). Re-run it any time you add videos; finished ones are skipped.
3. `python3 wall.py serve`, then open http://localhost:8000.
   - **Space** plays everyone together. **S** stops, **M** mutes, **F** goes full screen, **N** shows names.
   - **`** opens the debug menu: file names, moment controls, name boxes, and the ✎ Names page. It's off every time the page loads, so the gift view stays clean. In debug mode you can also fix a transcript.
   - Click a tile to see the full video. If the moment is off, use the nudge buttons or "Set to playhead".
   - A pink "set moment" badge means no "happy birthday" was found in that clip.
4. `python3 wall.py export` saves `export/happy-birthday-<name>.mp4`: a title card, the wall moment, then every message in full.

**Two videos from one person:** name them `Name_1.mov`, `Name_2.mov` (`_3` and up also work) and they join into one tile. For files that don't follow that naming, list them in `joins.json`, first file first, e.g. `[["a.mov", "b.mov"]]`.

**Your fixes are saved** in `names.json`, `sync_overrides.json` and `transcripts.json`, and they survive rebuilds.

**Want to test first?** `.venv/bin/python tools/make_test_clips.py` makes 24 fake robot-voice clips in `sample_videos/`. Then run `python3 wall.py build sample_videos`. Building from `videos/` again later clears the test build.

**Privacy:** `.gitignore` keeps videos, the build, and the export out of git. Don't commit real people's videos.
