// Birthday video wall. Data comes from manifest.js (window.WALL), written by `python3 wall.py build`.
const W = window.WALL;
const PAD = W.tilePad || 0;   // wall tiles begin with PAD seconds of frozen first frame (full videos don't)
const $ = (id) => document.getElementById(id);
const wall = $("wall");
let clips = W.clips;
let tiles = [];          // {clip, el, video}
let soundOn = true;
let playing = false;
let timers = [];
let current = -1;        // index open in the modal

$("title").textContent = W.title;
document.title = W.title;
$("count").textContent = `${clips.length} messages`;

// ---- grid ---------------------------------------------------------------------------
function layout(n, w, h) {
  let best = null;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    let cw = w / cols, ch = h / rows;
    if (cw / ch > W.maxAspect) cw = ch * W.maxAspect;
    if (ch / cw > W.maxAspect) ch = cw * W.maxAspect;
    const score = Math.min(cw, ch);
    if (!best || score > best.score + 0.01) best = { score, cols, rows, cw, ch };
  }
  return best;
}

function poster(c) { return `clips/${c.id}/poster.jpg?v=${c.sync}`; }

function buildTiles() {
  wall.innerHTML = "";
  tiles = clips.map((c, i) => {
    const el = document.createElement("div");
    el.className = "tile";
    el.style.background = c.color;
    const v = document.createElement("video");
    v.src = `clips/${c.id}/tile.mp4`;
    v.poster = poster(c);
    v.muted = true;
    v.playsInline = true;
    v.preload = "auto";
    el.append(v);
    el.insertAdjacentHTML("beforeend", `<span class="name"></span>`);
    setTileName(el, c.name);
    if (c.source === "missing") el.insertAdjacentHTML("beforeend", `<span class="flag" title="No 'happy birthday' found. Click to set it.">set moment</span>`);
    if (c.source === "guess") el.insertAdjacentHTML("beforeend", `<span class="flag guess" title="Heard 'birthday' but not 'happy birthday'. Click to check.">check moment</span>`);
    el.addEventListener("click", () => openModal(i));
    el.addEventListener("mouseenter", () => hoverPreview(i, true));
    el.addEventListener("mouseleave", () => hoverPreview(i, false));
    wall.append(el);
    return { clip: c, el, video: v };
  });
  place();
}

function setTileName(el, name) {
  const tag = el.querySelector(".name");
  tag.textContent = name;
  tag.hidden = !name;
}

function updateNameCount() {
  const named = clips.filter((c) => c.name).length;
  $("names-link").textContent = `✎ Names ${named}/${clips.length}`;
}

function place() {
  const w = wall.clientWidth, h = wall.clientHeight, gap = W.gap;
  const n = Math.max(1, tiles.length);
  const { cols, rows, cw, ch } = layout(n, w, h);
  const ox = (w - cols * cw) / 2, oy = (h - rows * ch) / 2;
  wall.querySelectorAll(".filler").forEach((f) => f.remove());
  const pos = (el, i) => {
    const r = Math.floor(i / cols), k = i % cols;
    Object.assign(el.style, { left: `${ox + k * cw + gap / 2}px`, top: `${oy + r * ch + gap / 2}px`,
      width: `${cw - gap}px`, height: `${ch - gap}px` });
  };
  tiles.forEach((t, i) => pos(t.el, i));
  for (let i = tiles.length; i < cols * rows; i++) {   // fill leftover cells so the wall is solid
    const f = document.createElement("div");
    f.className = "tile filler";
    f.style.background = W.clips.length ? clips[i % clips.length].color : "#333";
    f.textContent = ["🎂", "🎉", "🎈", "🥳"][i % 4];
    pos(f, i);
    wall.append(f);
  }
}
window.addEventListener("resize", place);

// ---- play together ------------------------------------------------------------------
function seekTo(v, t) {
  return new Promise((res) => {
    const done = () => { v.removeEventListener("seeked", done); res(); };
    if (v.readyState >= 1 && Math.abs(v.currentTime - t) < 0.01) return res();
    v.addEventListener("seeked", done);
    v.currentTime = t;
    setTimeout(done, 4000);  // never hang on one stubborn clip
  });
}

function waitReady(v) {
  return new Promise((res) => {
    if (v.readyState >= 3) return res();
    const done = () => { v.removeEventListener("canplay", done); res(); };
    v.addEventListener("canplay", done);
    setTimeout(done, 4000);
  });
}

async function playTogether() {
  stopAll();
  closeModal();
  playing = true;
  $("play").textContent = "… loading";
  const n = tiles.length;
  const vol = Math.min(1, 1.6 / Math.sqrt(n));
  // unlock audio inside the click (Safari wants this per video)
  tiles.forEach(({ video }) => { video.muted = !soundOn; video.volume = 0; video.play().catch(() => {}); video.pause(); });
  const plan = tiles.map(({ clip, video }) => {
    const start = PAD + clip.sync - W.lead;   // with the pad, this is never below 0
    return { video, ss: Math.max(0, start), delay: Math.max(0, -start) };
  });
  await Promise.all(plan.map((p) => seekTo(p.video, p.ss).then(() => waitReady(p.video))));
  if (!playing) return;
  $("play").textContent = "↻ Again";
  runTogether(plan, vol);
}

// One loop drives the whole run. The clips that start right away set the clock ("pack time"): when
// ~70 videos start at once they all start a little late together, so following them (not the wall
// clock) keeps the early clips, the fade and the cutoff exactly in step with what's on screen.
function runTogether(plan, vol) {
  const CRAWL = 0.0625;   // slowest speed browsers allow
  const total = W.lead + W.after;
  plan.forEach((p) => {
    // tiles carry a 1.5s lead-in pad, so nobody waits; this crawl is only a fallback if the pad is
    // ever shorter than the lead-in (a clip crawls silently until its turn instead of a laggy late start)
    p.waiting = p.delay > 0;
    p.video.playbackRate = p.waiting ? CRAWL : 1;
    p.video.volume = p.waiting ? 0 : vol;
    p.video.play().catch(() => {});
  });
  const t0 = performance.now();
  let lastE = 0, lastNow = t0, popped = false;
  const loop = () => {
    if (!playing) return;
    const now = performance.now();
    const pack = plan.filter((p) => p.delay === 0 && !p.video.paused && !p.video.ended && !p.video.seeking)
      .map((p) => p.video.currentTime - p.ss).sort((a, b) => a - b);
    let E = pack.length ? pack[Math.floor(pack.length / 2)] : lastE + (now - lastNow) / 1000;
    E = Math.max(E, lastE);
    lastE = E; lastNow = now;
    const fade = Math.max(0, Math.min(1, (total - E) / 0.5));   // sound fades over the last half second
    plan.forEach((p) => {
      if (p.waiting) {
        if (E < p.delay) return;
        p.waiting = false;   // its turn: full speed, sound on
      }
      p.video.volume = vol * fade;
      if (p.video.paused || p.video.ended || p.video.seeking) return;
      // gently speed up / slow down anyone off the pack (pitch is preserved)
      const drift = p.ss + (E - p.delay) - p.video.currentTime;   // + = behind
      p.video.playbackRate = Math.abs(drift) > 0.04 ? 1 + Math.max(-0.15, Math.min(0.15, drift * 1.5)) : 1;
    });
    if (!popped && E >= W.lead) {
      popped = true;
      wall.classList.remove("pop"); void wall.offsetWidth; wall.classList.add("pop");
    }
    if (E >= total || now - t0 > (total + 5) * 1000) {   // W.after seconds after the moment: freeze, then reset
      plan.forEach((p) => p.video.pause());
      timers.push(setTimeout(stopAll, 1500));
      return;
    }
    timers.push(setTimeout(loop, 30));
  };
  timers.push(setTimeout(loop, 30));
}

function stopAll() {
  playing = false;
  timers.forEach(clearTimeout);
  timers = [];
  $("play").textContent = "▶ Play together";
  tiles.forEach(({ clip, video }) => {
    video.pause();
    video.muted = true;
    video.playbackRate = 1;
    video.currentTime = PAD + clip.sync + 0.3;
  });
}

function hoverPreview(i, on) {
  if (playing) return;
  const { clip, video } = tiles[i];
  if (on) {
    video.muted = true;
    video.currentTime = PAD + Math.max(0, clip.sync - 0.6);
    video.play().catch(() => {});
  } else {
    video.pause();
    video.currentTime = PAD + clip.sync + 0.3;
  }
}

// ---- modal: full video + sync tweaks ------------------------------------------------
const full = $("full");
let checkTimer = null;

function openModal(i) {
  if (playing) stopAll();
  if (current >= 0) saveName();
  if (document.activeElement?.id === "m-transcript-edit") document.activeElement.blur();  // saves it
  current = (i + tiles.length) % tiles.length;
  const c = clips[current];
  $("modal").hidden = false;
  $("m-name").value = c.name;
  $("m-title").textContent = c.name;
  $("m-file").textContent = c.display || c.file;
  $("m-transcript").textContent = c.transcript ? `“${c.transcript}”` : "";
  $("m-transcript-box").classList.toggle("empty", !c.transcript);
  $("m-transcript-edit").value = c.transcript || "";
  showTranscriptState();
  $("m-status").textContent = "";
  full.src = `clips/${c.id}/full.mp4`;
  full.muted = false;
  full.play().catch(() => {});
  showSync();
}

function showSync() {
  const c = clips[current];
  $("m-sync").textContent = `${c.sync.toFixed(2)}s`;
  const src = $("m-source");
  src.className = c.source;
  src.textContent = { auto: "found automatically", manual: "set by you", guess: "a guess (heard “birthday” but not “happy birthday”). Check it", missing: "not found. Scrub to it and press “Set to playhead”" }[c.source];
  $("m-reset").hidden = c.source !== "manual" || c.auto == null;
}

function closeModal() {
  if (current >= 0) saveName();
  if (document.activeElement?.id === "m-transcript-edit") document.activeElement.blur();  // saves it
  $("modal").hidden = true;
  full.pause();
  full.removeAttribute("src");
  full.load();
  current = -1;
}

async function saveSync(value) {
  const c = clips[current];
  const status = $("m-status");
  status.className = "status";
  status.textContent = "saving…";
  try {
    const r = await fetch("api/sync", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file, sync: value }) });
    if (!r.ok) throw new Error(r.status);
    const updated = await r.json();
    Object.assign(c, updated);
    status.textContent = "saved";
  } catch (e) {
    if (value != null) { c.sync = Math.max(0, value); c.source = "manual"; }
    status.className = "status err";
    status.textContent = "Not saved. Open the wall with “python3 wall.py serve” to keep changes.";
  }
  const t = tiles[current];
  t.video.poster = poster(c);
  t.video.currentTime = PAD + c.sync + 0.3;
  t.el.querySelector(".flag")?.remove();
  showSync();
}

document.querySelectorAll("[data-nudge]").forEach((b) =>
  b.addEventListener("click", () => {
    const c = clips[current];
    saveSync(Math.max(0, +(c.sync + +b.dataset.nudge).toFixed(2)));
    checkIt();
  }));
$("m-here").addEventListener("click", () => saveSync(+full.currentTime.toFixed(2)));
$("m-reset").addEventListener("click", () => saveSync(null));
$("m-check").addEventListener("click", checkIt);

function checkIt() {  // play 1.5s before the moment to 2s after
  const c = clips[current];
  clearTimeout(checkTimer);
  full.currentTime = Math.max(0, c.sync - 1.5);
  full.play().catch(() => {});
  checkTimer = setTimeout(() => full.pause(), 3500);
}

async function saveName() {
  const c = clips[current];
  const name = $("m-name").value.trim();
  if (!c || name === c.name) return;
  const status = $("m-status");
  try {
    const r = await fetch("api/name", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file, name }) });
    if (!r.ok) throw new Error(r.status);
    c.name = name;
    if (clips[current] === c) $("m-title").textContent = name;
    setTileName(tiles[clips.indexOf(c)].el, name);
    updateNameCount();
  } catch (e) {
    status.className = "status err";
    status.textContent = "Name not saved. Open the wall with “python3 wall.py serve”.";
  }
}
$("m-name").addEventListener("change", saveName);

function showTranscriptState(msg) {
  const c = clips[current];
  if (!c) return;
  const st = $("m-transcript-status");
  st.className = "status";
  st.textContent = msg || (!c.transcriptEdited ? "automatic" : c.transcript ? "edited by you" : "hidden (no transcript shown)");
  $("m-transcript-reset").hidden = !c.transcriptEdited;
}

async function saveTranscript(text) {
  const c = clips[current];
  if (!c) return;
  try {
    const r = await fetch("api/transcript", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: c.file, text }) });
    if (!r.ok) throw new Error(r.status);
    Object.assign(c, await r.json());
    if (clips[current] === c) {
      $("m-transcript").textContent = c.transcript ? `“${c.transcript}”` : "";
      $("m-transcript-box").classList.toggle("empty", !c.transcript);
      $("m-transcript-edit").value = c.transcript || "";
      showTranscriptState(text == null ? "reset to automatic" : "saved");
    }
  } catch (e) {
    const st = $("m-transcript-status");
    st.className = "status err";
    st.textContent = "Not saved. Open with “python3 wall.py serve”.";
  }
}
$("m-transcript-edit").addEventListener("change", (e) => {
  const c = clips[current];
  const text = e.target.value.trim();
  if (text === (c.transcript || "").trim()) return;
  // clearing the box, or typing back exactly what Whisper heard, means "use the automatic one"
  saveTranscript(text && text !== (c.transcriptAuto || "").trim() ? text : null);
});
$("m-transcript-reset").addEventListener("click", () => saveTranscript(null));

$("close").addEventListener("click", closeModal);
$("modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
$("prev").addEventListener("click", () => openModal(current - 1));
$("next").addEventListener("click", () => openModal(current + 1));

// ---- bar buttons + keys --------------------------------------------------------------
$("play").addEventListener("click", playTogether);
$("stop").addEventListener("click", stopAll);
$("sound").addEventListener("click", () => {
  soundOn = !soundOn;
  $("sound").textContent = soundOn ? "🔊 Sound on" : "🔇 Muted";
  if (playing) tiles.forEach(({ video }) => (video.muted = !soundOn));
});
$("fs").addEventListener("click", () =>
  document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen());
document.addEventListener("fullscreenchange", () => {
  document.body.classList.toggle("fs", !!document.fullscreenElement);
  requestAnimationFrame(place);
});
document.addEventListener("mousemove", (e) => document.body.classList.toggle("show-bar", e.clientY < 70));

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") {   // typing a name: Enter/Esc just finish the field
    if (e.key === "Enter" || e.key === "Escape") e.target.blur();
    return;
  }
  if (e.target.tagName === "TEXTAREA") {   // editing a transcript: Esc finishes (and saves)
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "`") {   // debug menu: file names, sync moments, names, badges
    const on = document.body.classList.toggle("debug");
    if (!on && document.activeElement?.blur) document.activeElement.blur();
    return;
  }
  const open = !$("modal").hidden;
  if (e.key === "Escape" && open) return closeModal();
  if (open && e.key === "ArrowLeft") return openModal(current - 1);
  if (open && e.key === "ArrowRight") return openModal(current + 1);
  if (open) return;
  if (e.key === " ") { e.preventDefault(); playTogether(); }
  if (e.key === "s") stopAll();
  if (e.key === "m") $("sound").click();
  if (e.key === "f") $("fs").click();
  if (e.key === "n") document.body.classList.toggle("names");
});

document.body.insertAdjacentHTML("beforeend", `<div id="debug-pill">Debug on · press \` to hide</div>`);
buildTiles();
updateNameCount();
