"""Make fake birthday-message clips for testing the wall.

Each clip is a colored card with a cartoon face and a spoken message (macOS `say`).
The mouth opens and "HAPPY BIRTHDAY!" appears at the exact moment the voice says it,
so you can see by eye whether the wall lines everyone up.

Usage:  .venv/bin/python tools/make_test_clips.py [out_dir]   (default: sample_videos/)
"""
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RECIPIENT = "Alex"   # keep this the same as RECIPIENT in wall.py
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_videos")
FONT = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"

COLORS = ["#6f7fb3", "#d6261f", "#f08a12", "#f4b98a", "#8fbf9f", "#2e9e48", "#c95a7a",
          "#1f3fa6", "#7cc242", "#2f6fd6", "#b02fbf", "#1f9a8f", "#e0245e", "#6a2fa0",
          "#e83a9a", "#f2c48f", "#2aa7e8", "#f5c518", "#e8302a", "#22a39a", "#8fa8c8",
          "#f39a1e", "#3d7a5e", "#2f7fe0"]

# name, voice, lead-in line, trailing line, size, container
PEOPLE = [
    ("Uncle Bob", "Fred", f"Hey {RECIPIENT}, it's Bob. I'm sitting in the car right now.", "Hope it's a great one.", "v", "mov"),
    ("Aunt Sarah", "Samantha", "Hi sweetie!", "We love you so much.", "v", "mp4"),
    ("Grandma June", "Grandma (English (US))", f"{RECIPIENT}, darling, Grandpa is holding the phone for me.", "Call me later!", "v", "mov"),
    ("Priya", "Rishi", f"Okay is it recording? Okay. Hi {RECIPIENT}!", "Drinks are on me this weekend.", "v", "mp4"),
    ("Marcus", "Daniel", f"{RECIPIENT}. Another trip around the sun.", "Cheers.", "h", "mp4"),
    ("The Lees", "Karen", "Hi from all of us here in Portland! Say hi kids!", "Bye!", "h", "m4v"),
    ("Moira", "Moira", "Hello hello.", "Have a wee dram for me.", "v", "webm"),
    ("Tess", "Tessa", f"{RECIPIENT}! I can't believe you're another year older. Honestly. Wild.", "Love you.", "v", "mov"),
    ("Coach Ralph", "Ralph", f"{RECIPIENT}, this is Coach. Proud of you, kid.", "Now go run a mile.", "v", "mp4"),
    ("Shelley", "Shelley (English (US))", f"Hi {RECIPIENT}, I'm at work so I have to be quick.", "Okay bye!", "v", "mp4"),
    ("Reed", "Reed (English (US))", "Yo.", "That's it, that's the message.", "s", "mp4"),
    ("Sandy", "Sandy (English (UK))", f"{RECIPIENT}! Greetings from London, it is, of course, raining.", "Miss you loads.", "v", "mov"),
    ("Albert", "Albert", f"Greetings, {RECIPIENT}. I have prepared a short statement.", "End of statement.", "v", "avi"),
    ("Flo", "Flo (English (US))", f"Hi {RECIPIENT}, it's Flo from the book club.", "We'll save you a seat.", "v", "mp4"),
    ("Eddy", "Eddy (English (UK))", f"Alright {RECIPIENT}.", "Have a good one.", "h", "mp4"),
    ("Junior", "Junior", f"Hi Auntie {RECIPIENT}! Mom said I have to say it slowly.", "Can I have cake?", "v", "mp4"),
    ("Kathy", "Kathy", "Hey girl. So I had a whole speech planned and I forgot it.", "Anyway.", "v", "mov"),
    ("Rocko", "Rocko (English (US))", f"What's up {RECIPIENT}.", "Party at yours?", "v", "mp4"),
    ("Grandpa Lou", "Grandpa (English (US))", f"Is this thing on? June, is it on? Alright. {RECIPIENT}.", "Love, Grandpa.", "v", "mov"),
    ("Superstar Sam", "Superstar", "This is a very special message for a very special person.", "Thank you, thank you.", "v", "mp4"),
    ("Jess (no phrase)", "Samantha", f"{RECIPIENT}! Many happy returns of the day!", "Thinking of you.", "v", "mp4"),
    ("Dan", "Daniel", f"Hi {RECIPIENT}, it's Dan, from the office, the one with the plant.", "See you Monday.", "v", "mov"),
    ("Rotated iPhone", "Karen", f"Hi {RECIPIENT}, this one is filmed sideways on purpose.", "Testing, testing.", "rot", "mov"),
    ("HEVC Phone", "Tessa", f"{RECIPIENT}, this is an iPhone style video.", "Big hugs.", "hevc", "mov"),
]

PHRASE = f"Happy birthday, {RECIPIENT}!"
NO_PHRASE_NAMES = {"Jess (no phrase)"}


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def card(size, color, name, phase):
    """phase: 'talk' (mouth small), 'hb' (mouth open + banner), 'after'."""
    w, h = size
    img = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(img)
    s = min(w, h)
    cx, cy = w // 2, int(h * 0.42)
    r = int(s * 0.28)
    # head
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#ffd9b8", outline="#2b1d14", width=max(4, s // 120))
    # eyes
    er = max(6, r // 9)
    for ex in (cx - r // 2.6, cx + r // 2.6):
        d.ellipse([ex - er, cy - r // 4 - er, ex + er, cy - r // 4 + er], fill="#2b1d14")
    # mouth
    mw = r // 2
    if phase == "hb":
        d.ellipse([cx - mw, cy + r // 6, cx + mw, cy + r // 6 + int(mw * 1.3)], fill="#5a1a1a")
    else:
        d.line([cx - mw // 2, cy + r // 2.5, cx + mw // 2, cy + r // 2.5], fill="#2b1d14", width=max(5, s // 90))
    big = ImageFont.truetype(FONT, int(s * 0.085))
    small = ImageFont.truetype(FONT, int(s * 0.045))
    d.text((cx, int(h * 0.80)), name, font=big, fill="white", anchor="mm", stroke_width=3, stroke_fill="#00000055")
    d.text((cx, int(h * 0.88)), "test clip", font=small, fill="#ffffffaa", anchor="mm")
    if phase == "hb":
        banner = ImageFont.truetype(FONT, int(s * 0.10))
        d.text((cx, int(h * 0.10)), "HAPPY", font=banner, fill="white", anchor="mm", stroke_width=5, stroke_fill="#000")
        d.text((cx, int(h * 0.10) + int(s * 0.11)), "BIRTHDAY!", font=banner, fill="white", anchor="mm", stroke_width=5, stroke_fill="#000")
    return img


def make(i, person, tmp, truth):
    name, voice, lead, trail, shape, ext = person
    color = COLORS[i % len(COLORS)]
    size = {"v": (1080, 1920), "h": (1920, 1080), "s": (1080, 1080),
            "rot": (1080, 1920), "hevc": (1080, 1920)}[shape]
    t = Path(tmp) / f"c{i}"
    t.mkdir()
    phrase = f"Many happy returns, {RECIPIENT}!" if name in NO_PHRASE_NAMES else PHRASE
    if name in NO_PHRASE_NAMES:
        lead = f"{RECIPIENT}!"
    run(["say", "-v", voice, "-o", str(t / "a.aiff"), lead])
    run(["say", "-v", voice, "-o", str(t / "b.aiff"), phrase])
    run(["say", "-v", voice, "-o", str(t / "c.aiff"), trail])
    da, db, dc = (duration(t / f"{k}.aiff") for k in "abc")
    pre = round(random.uniform(0.4, 2.5), 2)   # silence before talking, like fumbling the phone
    gap = 0.35
    moment = pre + da + gap
    total = moment + db + gap + dc + 0.8
    # audio track
    run(["ffmpeg", "-y", "-f", "lavfi", "-t", str(pre), "-i", "anullsrc=r=44100:cl=mono",
         "-i", str(t / "a.aiff"), "-f", "lavfi", "-t", str(gap), "-i", "anullsrc=r=44100:cl=mono",
         "-i", str(t / "b.aiff"), "-f", "lavfi", "-t", str(gap), "-i", "anullsrc=r=44100:cl=mono",
         "-i", str(t / "c.aiff"), "-f", "lavfi", "-t", "0.8", "-i", "anullsrc=r=44100:cl=mono",
         "-filter_complex", "[0][1][2][3][4][5][6]concat=n=7:v=0:a=1,aresample=44100[a]",
         "-map", "[a]", str(t / "audio.wav")])
    # three still frames, timed with the concat demuxer
    for ph in ("talk", "hb", "after"):
        im = card(size, color, name, ph)
        if shape == "rot":
            im = im.rotate(90, expand=True)  # stored sideways; rotation flag fixes it on playback
        im.save(t / f"{ph}.png")
    (t / "frames.txt").write_text(
        f"file '{t}/talk.png'\nduration {moment:.3f}\n"
        f"file '{t}/hb.png'\nduration {db:.3f}\n"
        f"file '{t}/after.png'\nduration {total - moment - db:.3f}\n"
        f"file '{t}/after.png'\n")
    out = OUT / f"{name}.{ext}"
    vin = ["-f", "concat", "-safe", "0", "-i", str(t / "frames.txt"), "-i", str(t / "audio.wav")]
    common = ["-r", "30", "-pix_fmt", "yuv420p", "-shortest"]
    if ext == "webm":
        enc = ["-c:v", "libvpx-vp9", "-b:v", "1M", "-c:a", "libopus"]
    elif ext == "avi":
        enc = ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "pcm_s16le"]
    elif shape == "hevc":
        enc = ["-c:v", "hevc_videotoolbox", "-b:v", "4M", "-tag:v", "hvc1", "-c:a", "aac"]
    else:
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac"]
    if shape == "rot":
        tmpv = t / "sideways.mp4"
        run(["ffmpeg", "-y", *vin, *common, *enc, str(tmpv)])
        run(["ffmpeg", "-y", "-display_rotation:v", "-90", "-i", str(tmpv), "-c", "copy", str(out)])
    else:
        run(["ffmpeg", "-y", *vin, *common, *enc, str(out)])
    truth[out.name] = None if name in NO_PHRASE_NAMES else round(moment, 2)
    print(f"  {out.name:28s} happy birthday at {moment:5.2f}s  (clip {total:4.1f}s)")


def main():
    random.seed(7)
    OUT.mkdir(exist_ok=True)
    truth = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i, p in enumerate(PEOPLE):
            make(i, p, tmp, truth)
    (OUT / "_ground_truth.json").write_text(json.dumps(truth, indent=2))
    print(f"Made {len(PEOPLE)} clips in {OUT}/")


if __name__ == "__main__":
    main()
