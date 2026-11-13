#!/usr/bin/env python3
"""Birthday video wall.

  python3 wall.py build [folder]   convert videos + find "happy birthday" in each  (default folder: videos/)
  python3 wall.py serve            open the wall at http://localhost:8000 (sync tweaks get saved)
  python3 wall.py export           render one video file: title card, the wall moment, then every message in full

Original videos are never modified. Everything generated goes in build/ and export/.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_VENV = ROOT / ".venv"
if (_VENV / "bin/python").exists() and Path(sys.prefix).resolve() != _VENV.resolve():
    os.execv(str(_VENV / "bin/python"), [str(_VENV / "bin/python"), __file__, *sys.argv[1:]])

import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# ---- settings you might want to change -------------------------------------------------
RECIPIENT = "Alex"   # the birthday person's name
TITLE = f"Happy Birthday, {RECIPIENT}"
LEAD = 1.5           # seconds of each clip shown before everyone says "happy birthday"
WALL_AFTER = 3.0     # seconds "Play together" (and the export's wall) keeps going after the moment
WHISPER_MODEL = "small.en"
EXPORT_W, EXPORT_H = 1920, 1080
GAP = 4              # black gap between tiles, in pixels
MAX_TILE_ASPECT = 1.18  # tiles may stretch this far from square so the wall fills the screen
COLORS = ["#6f7fb3", "#d6261f", "#f08a12", "#f4b98a", "#8fbf9f", "#2e9e48", "#c95a7a",
          "#1f3fa6", "#7cc242", "#2f6fd6", "#b02fbf", "#1f9a8f", "#e0245e", "#6a2fa0",
          "#e83a9a", "#f2c48f", "#2aa7e8", "#f5c518", "#e8302a", "#22a39a"]
# -----------------------------------------------------------------------------------------

TILE_PAD = LEAD   # wall tiles start with this much frozen first frame, so every clip can start at once
BUILD = ROOT / "build"
CLIPS = BUILD / "clips"
WEB = ROOT / "web"
EXPORT = ROOT / "export"
OVERRIDES = ROOT / "sync_overrides.json"
JOINS = ROOT / "joins.json"   # lists of files to play back to back as one clip
NAMES = ROOT / "names.json"
TRANSCRIPTS = ROOT / "transcripts.json"   # file name -> hand-fixed transcript (replaces Whisper's)   # file name -> person's name (blank = no name tag)
CACHE = BUILD / "cache.json"
FONT = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"


# ---- helpers -----------------------------------------------------------------------------
def run(cmd, quiet=True):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:6]))} ...\n{r.stderr[-2000:]}")
    return r.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    return json.loads(out)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "clip"


def even(x):
    return max(2, int(round(x / 2)) * 2)


def grid_layout(n, w, h):
    """Pick columns/rows so the tiles are as big as possible (near-square)."""
    best = None
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cw, ch = w / cols, h / rows
        if cw / ch > MAX_TILE_ASPECT:
            cw = ch * MAX_TILE_ASPECT
        if ch / cw > MAX_TILE_ASPECT:
            ch = cw * MAX_TILE_ASPECT
        score = min(cw, ch)
        if best is None or score > best[0] + 0.01:
            best = (score, cols, rows, cw, ch)
    _, cols, rows, cw, ch = best
    return cols, rows, cw, ch


# ---- build -------------------------------------------------------------------------------
def video_info(path):
    """Return (display width, height, has_audio, is_hdr, duration) or None if not a video."""
    try:
        info = probe(path)
    except RuntimeError:
        return None
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    dur = float(info.get("format", {}).get("duration") or 0)
    if not v or dur < 0.5:
        return None
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int(v.get("tags", {}).get("rotate", rot))
    if abs(rot) % 180 == 90:
        w, h = h, w
    hdr = v.get("color_transfer") in ("arib-std-b67", "smpte2084")
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    return w, h, has_audio, hdr, dur


def transcode(src, out_dir, info):
    sdr = out_dir / "sdr.mov"
    if info[3] and shutil.which("avconvert"):
        # iPhone HDR: Apple's own converter gives natural color; ffmpeg's comes out washed out
        try:
            run(["avconvert", "--source", src, "--preset", "Preset1920x1080", "--output", sdr, "--replace"])
            src, info = sdr, video_info(sdr)
        except RuntimeError:
            sdr.unlink(missing_ok=True)
    try:
        return _transcode(src, out_dir, info)
    finally:
        sdr.unlink(missing_ok=True)


def _transcode(src, out_dir, info):
    w, h, has_audio, hdr, _ = info
    scale = min(1.0, 1920 / max(w, h), 1080 / min(w, h))
    fw, fh = even(w * scale), even(h * scale)
    full, tile = out_dir / "full.mp4", out_dir / "tile.mp4"
    color = "colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:fast=1," if hdr else ""  # fallback only
    vf = f"{color}scale={fw}:{fh}:flags=lanczos,setsar=1,fps=30,format=yuv420p"
    audio_in = [] if has_audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    amap = ["-map", "0:a:0"] if has_audio else ["-map", "1:a", "-shortest"]
    base = ["ffmpeg", "-y", "-v", "error", "-i", src, *audio_in, "-map", "0:v:0", *amap]
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
           "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]
    try:
        run([*base, "-vf", vf, *enc, full])
    except RuntimeError:
        if not hdr:
            raise
        run([*base, "-vf", vf.replace(color, ""), *enc, full])  # HDR fix failed: plain convert
    make_tile(out_dir, fw, fh)
    return fw, fh


def make_tile(out_dir, fw, fh):
    """Square tile, cropped a bit above center on tall videos (where faces usually are)."""
    full, tile = out_dir / "full.mp4", out_dir / "tile.mp4"
    side = min(fw, fh)
    x, y = (fw - side) // 2, int((fh - side) * (0.4 if fh > fw else 0.5))
    # a frozen first frame + silence up front: clips that say it in their first seconds still have a
    # lead-in, so "Play together" can start every tile at the same instant (delayed starts lag)
    run(["ffmpeg", "-y", "-v", "error", "-i", full,
         "-vf", f"crop={side}:{side}:{x}:{y},scale=480:480,tpad=start_duration={TILE_PAD}:start_mode=clone",
         "-af", f"adelay={int(TILE_PAD * 1000)}:all=1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-b:a", "96k",
         "-movflags", "+faststart", tile])
    (out_dir / "tile_pad.txt").write_text(str(TILE_PAD))


def find_joins(files):
    """joins.json groups, plus automatic ones: name_1, name_2, ... play back to back in number order.
    Only _1 to _99 with no leading zero, so phone names like IMG_1011 never match."""
    manual = [g for g in load_json(JOINS, []) if len(g) >= 2]
    taken = {f for g in manual for f in g}
    auto = {}
    for f in files:
        m = re.fullmatch(r"(.+)_([1-9]\d?)", Path(f).stem)
        if m and f not in taken:
            auto.setdefault(m.group(1).lower(), []).append((int(m.group(2)), f))
    groups = [[f for _, f in sorted(g)] for g in auto.values() if len(g) >= 2 and min(g)[0] == 1]
    return manual + groups


def join_clips(jid, members, src_dir):
    """Play several converted clips back to back as one clip (straight cut)."""
    out_dir = CLIPS / jid
    out_dir.mkdir(exist_ok=True)
    w, h = members[0][1]["w"], members[0][1]["h"]
    inputs, graph, chain, words, offset = [], [], "", [], 0.0
    for i, (cid, c) in enumerate(members):
        full = CLIPS / cid / "full.mp4"
        inputs += ["-i", full]
        graph.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30,format=yuv420p[v{i}]")
        chain += f"[v{i}][{i}:a]"
        words += [[round(a + offset, 2), round(b + offset, 2), t] for a, b, t in c["words"]]
        offset += float(probe(full)["format"]["duration"])
    graph.append(f"{chain}concat=n={len(members)}:v=1:a=1[v][a]")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_dir / "full.mp4"])
    make_tile(out_dir, w, h)
    first = members[0][1]
    return {"file": first["file"], "parts": [c["file"] for _, c in members],
            "sig": "+".join(c["sig"] for _, c in members), "order": first["order"], "src_dir": str(src_dir),
            "w": w, "h": h, "duration": round(offset, 2), "words": words}


_model = None


def transcribe(path):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print(f"  loading speech model ({WHISPER_MODEL}; first run downloads it)...", flush=True)
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    segments, _ = _model.transcribe(audio, word_timestamps=True, language="en",
                                    beam_size=5, condition_on_previous_text=False)
    words = []
    for seg in segments:
        for wd in seg.words or []:
            words.append([round(wd.start, 2), round(wd.end, 2), wd.word.strip()])
    return words


def find_happy_birthday(words):
    """Start of the first "happy birthday". Whisper's start time for "happy" drifts early when a
    pause comes before it, but "birthday" lands reliably, so step back from that (tested: ±0.1s)."""
    norm = [re.sub(r"[^a-z]", "", w[2].lower()) for w in words]
    for i, w in enumerate(norm):
        nxt = "".join(norm[i + 1:i + 3])
        if w.startswith("happybirth"):
            return words[i][0], True
        if w.startswith("happy") and (nxt.startswith("birth") or nxt.startswith("bday")):
            return round(max(0.0, words[i + 1][0] - 0.33), 2), True
    for i, w in enumerate(norm):  # heard "birthday" without "happy": a guess, flagged for a look
        if "birthday" in w or w == "bday":
            return round(max(0.0, words[i][0] - 0.4), 2), False
    return None, False


def poster(clip_dir, t):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, t) + TILE_PAD:.2f}", "-i", clip_dir / "tile.mp4",
         "-frames:v", "1", "-q:v", "3", clip_dir / "poster.jpg"])


def write_manifest(cache=None):
    cache = cache if cache is not None else load_json(CACHE, {})
    overrides = load_json(OVERRIDES, {})
    names = load_json(NAMES, {})
    fixed = load_json(TRANSCRIPTS, {})
    joined = {f for c in cache.values() for f in c.get("parts", [])}
    shown = [(cid, c) for cid, c in cache.items() if "parts" in c or c["file"] not in joined]
    clips = []
    for i, (cid, c) in enumerate(sorted(shown, key=lambda kv: kv[1]["order"])):
        c["auto"], sure = find_happy_birthday(c["words"])
        o = overrides.get(c["file"])
        if o is not None:
            sync, source = o, "manual"
        elif c["auto"] is not None:
            sync, source = c["auto"], ("auto" if sure else "guess")
        else:
            sync, source = 0.0, "missing"
        clips.append({
            "id": cid, "name": (names.get(c["file"]) or "").strip(), "file": c["file"], "w": c["w"], "h": c["h"],
            "duration": c["duration"], "sync": sync, "auto": c["auto"], "source": source,
            "color": COLORS[i % len(COLORS)], "display": " + ".join(c.get("parts", [c["file"]])),
            # a fix in transcripts.json wins; an explicit "" there means "show no transcript"
            "transcript": fixed[c["file"]] if c["file"] in fixed else " ".join(w[2] for w in c["words"]).strip(),
            "transcriptAuto": " ".join(w[2] for w in c["words"]).strip(),
            "transcriptEdited": c["file"] in fixed,
        })
    data = {"title": TITLE, "lead": LEAD, "after": WALL_AFTER, "tilePad": TILE_PAD, "gap": GAP, "maxAspect": MAX_TILE_ASPECT, "clips": clips}
    (BUILD / "manifest.json").write_text(json.dumps(data, indent=1))
    (BUILD / "manifest.js").write_text("window.WALL = " + json.dumps(data) + ";\n")
    return data


def copy_web():
    for f in WEB.iterdir():
        if f.is_file():
            shutil.copy2(f, BUILD / f.name)


def cmd_build(src_dir):
    src_dir = (ROOT / src_dir).resolve() if not Path(src_dir).is_absolute() else Path(src_dir)
    CLIPS.mkdir(parents=True, exist_ok=True)
    old = load_json(CACHE, {})
    if old and next(iter(old.values())).get("src_dir") != str(src_dir):
        print(f"Switching source folder to {src_dir.name}/, clearing old build.")
        shutil.rmtree(CLIPS)
        CLIPS.mkdir()
        old = {}
    files = sorted((p for p in src_dir.iterdir() if p.is_file() and not p.name.startswith((".", "_"))),
                   key=lambda p: p.name.lower())
    cache, used, skipped = {}, set(), []
    print(f"Building wall from {len(files)} files in {src_dir.name}/")
    for order, src in enumerate(files):
        st = src.stat()
        sig = f"{st.st_size}-{int(st.st_mtime)}"
        cid = slug(src.stem)
        while cid in used:
            cid += "-2"
        used.add(cid)
        out_dir = CLIPS / cid
        prev = old.get(cid)
        if prev and prev["sig"] == sig and (out_dir / "tile.mp4").exists():
            prev["order"] = order
            cache[cid] = prev
            print(f"  = {src.name} (unchanged)")
            continue
        info = video_info(src)
        if info is None:
            skipped.append(src.name)
            print(f"  ! {src.name}: not a video, skipped")
            continue
        t0 = time.time()
        out_dir.mkdir(exist_ok=True)
        fw, fh = transcode(src, out_dir, info)
        words = transcribe(out_dir / "full.mp4")
        auto, _ = find_happy_birthday(words)
        cache[cid] = {"file": src.name, "sig": sig, "order": order,
                      "src_dir": str(src_dir), "w": fw, "h": fh, "duration": round(info[4], 2),
                      "auto": auto, "words": words}
        found = f'"happy birthday" at {auto:.2f}s' if auto is not None else "NO \"happy birthday\" found - set it by hand"
        print(f"  + {src.name}: {found}  ({time.time() - t0:.0f}s)", flush=True)
        CACHE.write_text(json.dumps({**old, **cache}))  # keep not-yet-reached clips if the build is stopped
    by_file = {c["file"]: (cid, c) for cid, c in cache.items()}
    for group in find_joins(by_file):
        members = [by_file.get(f) for f in group]
        if len(group) < 2 or None in members:
            print(f"  ! join skipped, not found: {[f for f, m in zip(group, members) if m is None] or group}")
            continue
        jid = "join-" + members[0][0]
        sig = "+".join(c["sig"] for _, c in members)
        prev = old.get(jid)
        if prev and prev["sig"] == sig and (CLIPS / jid / "tile.mp4").exists():
            cache[jid] = {**prev, "order": members[0][1]["order"]}
            print(f"  = joined {' + '.join(group)} (unchanged)")
            continue
        cache[jid] = join_clips(jid, members, src_dir)
        print(f"  + joined {' + '.join(group)} ({cache[jid]['duration']:.1f}s)", flush=True)
    for gone in set(old) - set(cache):
        shutil.rmtree(CLIPS / gone, ignore_errors=True)
    # tiles made before the lead-in pad existed (or with a different pad) get remade; quick, small files
    stale = [(cid, c) for cid, c in cache.items()
             if not (CLIPS / cid / "tile_pad.txt").exists() or (CLIPS / cid / "tile_pad.txt").read_text() != str(TILE_PAD)]
    if stale:
        from concurrent.futures import ThreadPoolExecutor
        print(f"  remaking {len(stale)} wall tiles with a {TILE_PAD}s lead-in...", flush=True)
        with ThreadPoolExecutor(4) as pool:
            list(pool.map(lambda kv: make_tile(CLIPS / kv[0], kv[1]["w"], kv[1]["h"]), stale))
    CACHE.write_text(json.dumps(cache))
    data = write_manifest(cache)
    names = load_json(NAMES, {})  # one blank entry per tile, ready to fill in
    hidden = {f for c in cache.values() for f in c.get("parts", [])[1:]}
    names = {f: n for f, n in names.items() if n or f not in hidden}
    for c in data["clips"]:
        names.setdefault(c["file"], "")
    NAMES.write_text(json.dumps(dict(sorted(names.items(), key=lambda kv: kv[0].lower())), indent=2))
    for c in data["clips"]:
        poster(CLIPS / c["id"], c["sync"] + 0.3)
    copy_web()
    missing = [c["file"] for c in data["clips"] if c["source"] == "missing"]
    guesses = [c["file"] for c in data["clips"] if c["source"] == "guess"]
    print(f"\nDone: {len(data['clips'])} clips on the wall.")
    if missing:
        print("Needs a hand-set moment: " + ", ".join(missing))
    if guesses:
        print("Guessed (heard \"birthday\" but not \"happy birthday\"), worth a look: " + ", ".join(guesses))
    if skipped:
        print("Skipped (not video): " + ", ".join(skipped))
    print("Next: python3 wall.py serve")


# ---- serve -------------------------------------------------------------------------------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(BUILD), **k)

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = super().translate_path(path)
        rel = Path(p).relative_to(BUILD) if Path(p).is_relative_to(BUILD) else None
        if rel and len(rel.parts) == 1 and (WEB / rel).exists():
            return str(WEB / rel)  # live page files, so edits show without rebuilding
        return p

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):  # adds byte-range support so videos can seek (Safari needs it)
        rng = self.headers.get("Range")
        path = self.translate_path(self.path.split("?")[0])
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        size = os.path.getsize(path)
        start = int(m.group(1)) if m and m.group(1) else 0
        end = int(m.group(2)) if m and m.group(2) else size - 1
        if m and not m.group(1) and m.group(2):
            start, end = size - int(m.group(2)), size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return None
        f = open(path, "rb")
        f.seek(start)
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        try:
            while remaining > 0:
                chunk = source.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self._remaining = None

    def do_GET(self):
        if self.path.split("?")[0] == "/manifest.js":  # always fresh
            write_manifest()
        return super().do_GET()

    def do_POST(self):
        if self.path not in ("/api/sync", "/api/name", "/api/transcript"):
            return self.send_error(404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/transcript":
            fixed = load_json(TRANSCRIPTS, {})
            text = "\n".join(" ".join(ln.split()) for ln in str(body.get("text") or "").splitlines()).strip()
            if text:
                fixed[body["file"]] = text
            else:
                fixed.pop(body["file"], None)  # blank or reset: back to Whisper's version
            TRANSCRIPTS.write_text(json.dumps(fixed, indent=2, ensure_ascii=False))
            data = write_manifest()
            clip = next(c for c in data["clips"] if c["file"] == body["file"])
        elif self.path == "/api/name":
            names = load_json(NAMES, {})
            names[body["file"]] = str(body.get("name") or "").strip()
            NAMES.write_text(json.dumps(names, indent=2))
            data = write_manifest()
            clip = next(c for c in data["clips"] if c["file"] == body["file"])
        else:
            overrides = load_json(OVERRIDES, {})
            if body.get("sync") is None:
                overrides.pop(body["file"], None)
            else:
                overrides[body["file"]] = round(max(0.0, float(body["sync"])), 2)
            OVERRIDES.write_text(json.dumps(overrides, indent=2, sort_keys=True))
            data = write_manifest()
            clip = next(c for c in data["clips"] if c["file"] == body["file"])
            poster(CLIPS / clip["id"], clip["sync"] + 0.3)
        out = json.dumps(clip).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def cmd_serve(port=8000):
    if not (BUILD / "manifest.json").exists():
        sys.exit("Nothing built yet. Run: python3 wall.py build")
    copy_web()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Wall is up at http://localhost:{port}   (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ---- export ------------------------------------------------------------------------------
ENC_V = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30", "-pix_fmt", "yuv420p",
         "-video_track_timescale", "15360"]
ENC_A = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def text_png(path, lines, full_card=False):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (EXPORT_W, EXPORT_H), (11, 11, 18, 255) if full_card else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_card:
        for i, col in enumerate(COLORS):  # confetti stripe
            d.rectangle([i * EXPORT_W // len(COLORS), EXPORT_H - 28, (i + 1) * EXPORT_W // len(COLORS), EXPORT_H], fill=col)
        d.text((EXPORT_W / 2, EXPORT_H / 2 - 30), lines[0], font=ImageFont.truetype(FONT, 120), fill="white", anchor="mm")
        d.text((EXPORT_W / 2, EXPORT_H / 2 + 90), lines[1], font=ImageFont.truetype(FONT, 46), fill="#f5c518", anchor="mm")
    elif lines[0]:  # name tag (left off when the name is blank)
        f = ImageFont.truetype(FONT, 54)
        x0, y0, x1, y1 = d.textbbox((70, EXPORT_H - 90), lines[0], font=f, anchor="ls")
        d.rounded_rectangle([x0 - 28, y0 - 20, x1 + 28, y1 + 22], radius=22, fill=(0, 0, 0, 150))
        d.text((70, EXPORT_H - 90), lines[0], font=f, fill="white", anchor="ls")
    img.save(path)


def export_wall(clips, out, tmp):
    n = len(clips)
    cols, rows, cw, ch = grid_layout(n, EXPORT_W, EXPORT_H)
    gw, gh = cols * cw, rows * ch
    ox, oy = (EXPORT_W - gw) / 2, (EXPORT_H - gh) / 2
    dur = LEAD + WALL_AFTER
    tw, th = even(cw - GAP), even(ch - GAP)
    inputs, vf, af, layout = [], [], [], []
    for i, c in enumerate(clips):
        start = c["sync"] - LEAD
        delay, ss = max(0.0, -start), max(0.0, start)
        inputs += ["-ss", f"{ss:.3f}", "-t", f"{dur + 1:.3f}", "-i", CLIPS / c["id"] / "full.mp4"]
        side = min(c["w"], c["h"])
        x, y = (c["w"] - side) // 2, int((c["h"] - side) * (0.4 if c["h"] > c["w"] else 0.5))
        vf.append(f"[{i}:v]crop={side}:{side}:{x}:{y},scale={tw}:{th}:force_original_aspect_ratio=increase,"
                  f"crop={tw}:{th},setsar=1,fps=30,tpad=start_duration={delay:.3f}:start_mode=clone:"
                  f"stop_mode=clone:stop_duration={dur:.2f},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
        af.append(f"[{i}:a]aresample=48000,adelay={int(delay * 1000)}:all=1,apad,atrim=duration={dur:.3f},"
                  f"asetpts=PTS-STARTPTS[a{i}]")
        r, k = divmod(i, cols)
        layout.append(f"{int(ox + k * cw + GAP / 2)}_{int(oy + r * ch + GAP / 2)}")
    fade = f"afade=t=out:st={dur - 0.5:.2f}:d=0.5"
    if n == 1:
        stack = f"[v0]pad={EXPORT_W}:{EXPORT_H}:{layout[0].replace('_', ':')}:black[vout]"
        amix = f"[a0]loudnorm=I=-16:TP=-1.5,{fade}[aout]"
    else:
        # xstack's canvas is the bounding box of the tiles; pad it out to the full frame
        stack = (f"{''.join(f'[v{i}]' for i in range(n))}xstack=inputs={n}:layout={'|'.join(layout)}:fill=black,"
                 f"pad={EXPORT_W}:{EXPORT_H}:0:0:black[vout]")
        amix = (f"{''.join(f'[a{i}]' for i in range(n))}amix=inputs={n}:normalize=1:dropout_transition=0,"
                f"loudnorm=I=-16:TP=-1.5,{fade}[aout]")
    graph = ";\n".join(vf + af + [stack, amix])
    gfile = Path(tmp) / "wall.txt"
    gfile.write_text(graph)
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", gfile, "-map", "[vout]",
         "-map", "[aout]", "-t", f"{dur:.3f}", *ENC_V, *ENC_A, out])


def export_message(c, out, tmp):
    label = Path(tmp) / f"label-{c['id']}.png"
    text_png(label, [c["name"]])
    graph = (f"[0:v]split[a][b];[a]scale={EXPORT_W}:{EXPORT_H}:force_original_aspect_ratio=increase,"
             f"crop={EXPORT_W}:{EXPORT_H},gblur=sigma=40,eq=brightness=-0.18[bg];"
             f"[b]scale={EXPORT_W}:{EXPORT_H}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2[m];[m][1:v]overlay=0:0,format=yuv420p[v];"
             f"[0:a]loudnorm=I=-16:TP=-1.5,aresample=48000[aout]")
    run(["ffmpeg", "-y", "-v", "error", "-i", CLIPS / c["id"] / "full.mp4", "-i", label,
         "-filter_complex", graph, "-map", "[v]", "-map", "[aout]", *ENC_V, *ENC_A, out])


def cmd_export():
    data = write_manifest()
    clips = data["clips"]
    if not clips:
        sys.exit("No clips. Run: python3 wall.py build")
    missing = [c["file"] for c in clips if c["source"] == "missing"]
    if missing:
        print("Heads up, no \"happy birthday\" moment set for: " + ", ".join(missing) + " (they start from 0s on the wall)")
    EXPORT.mkdir(exist_ok=True)
    final = EXPORT / f"{slug(TITLE)}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        segs = []
        card = Path(tmp) / "title.png"
        text_png(card, [TITLE, f"{len(clips)} messages from people who love you"], full_card=True)
        segs.append(Path(tmp) / "00-title.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", "3", "-i", card, "-f", "lavfi", "-t", "3",
             "-i", "anullsrc=r=48000:cl=stereo", "-vf", "format=yuv420p", *ENC_V, *ENC_A, segs[-1]])
        print(f"Rendering the wall ({len(clips)} tiles)...", flush=True)
        segs.append(Path(tmp) / "01-wall.mp4")
        export_wall(clips, segs[-1], tmp)
        for i, c in enumerate(clips):
            print(f"  message {i + 1}/{len(clips)}: {c['name']}", flush=True)
            segs.append(Path(tmp) / f"{i + 2:03d}-msg.mp4")
            export_message(c, segs[-1], tmp)
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs))
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
             "-movflags", "+faststart", final])
    total = float(probe(final)["format"]["duration"])
    print(f"\nSaved {final.relative_to(ROOT)}  ({total / 60:.1f} min)")


# ---- main --------------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd == "build":
        cmd_build(args[1] if len(args) > 1 else "videos")
    elif cmd == "serve":
        cmd_serve(int(args[1]) if len(args) > 1 else 8000)
    elif cmd == "export":
        cmd_export()
    else:
        print(__doc__)
