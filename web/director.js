// The demo video, as a pure function of time: renderAt(t) draws frame t.
// Scene timing comes from video/timeline.json (when each narration line
// plays); the live-run scenes replay the real Band transcript, with each
// message landing on the narration line that describes it.

import { CAST, blinkEyes, character } from "./art.js";
import { buildModel } from "./model.js";
import { Onsen } from "./onsen.js";

const clamp01 = (x) => Math.max(0, Math.min(1, x));
const easeOut = (x) => 1 - Math.pow(1 - clamp01(x), 3);
const backOut = (x) => {
  x = clamp01(x);
  return 1 + 2.9 * Math.pow(x - 1, 3) + 1.9 * Math.pow(x - 1, 2);
};
const pop = (t, at, dur = 0.45) => ({ k: backOut((t - at) / dur), o: clamp01((t - at) / 0.18) });

const HOST_HTML = `
  <div class="host">
    <div class="host-eyebrow">On camera</div>
    <div class="host-ring"></div>
    <div class="host-away">on the big screen</div>
    <div class="host-name">Mochi 🍊</div>
    <div class="host-role">head buyer · Masky avatar</div>
    <div class="host-bars">${"<i></i>".repeat(7)}</div>
    <div class="host-label">The rest of the herd</div>
    <div class="host-herd">${["Tofu", "Yuzu", "Shelly", "Zippy", "Foxy"].map((n) => `<div data-name="${n}"></div>`).join("")}</div>
    <div class="host-by">faces &amp; voices by</div>
    <div class="host-masky">Masky</div>
  </div>
  <img class="cam" alt="Mochi's Masky avatar">
  <div class="cam-tag">🎭 Mochi · on Masky</div>
  <div class="cam-ask">📱 What the owner sees: Mochi asks on Masky</div>`;

// The v2 cut (?cut=v2) is hosted by Mochi on Masky: the demo plays on a screen,
// Mochi's lip-synced Masky avatar narrates from a face-cam beside it, scene 3.5
// introduces the avatar, and scene 6.5 is Mochi's real approval clip.
export async function createDirector(root, { cut = "" } = {}) {
  const v2 = cut === "v2";
  const [timeline, transcript] = await Promise.all([
    fetch(`../video/timeline${cut ? `-${cut}` : ""}.json`).then((r) => r.json()),
    fetch("../runs/demo-transcript.json").then((r) => r.json()),
  ]);
  const model = buildModel(transcript);
  const scene = (n) => timeline.scenes.find((s) => s.n === n);
  const cue = (n, phrase) => {
    // v2 moves a few phrases into new scenes (6.6), so fall back to any scene.
    const s = [scene(n), ...timeline.scenes].find((x) => x && x.text.includes(phrase));
    if (!s) throw new Error(`cue not found: ${phrase}`);
    return s.start + (s.text.indexOf(phrase) / s.text.length) * (s.end - s.start);
  };
  const visualStart = (n) => (n === 1 ? 0 : scene(n).start - 0.35);
  const maskyScene = v2 && scene(3.5);
  const WINDOWS = [
    { id: "title", from: 0, to: visualStart(2) },
    { id: "problem", from: visualStart(2), to: visualStart(3) },
    { id: "herd", from: visualStart(3), to: visualStart(maskyScene ? 3.5 : 4) },
    ...(maskyScene ? [{ id: "masky", from: visualStart(3.5), to: visualStart(4) }] : []),
    { id: "run", from: visualStart(4), to: visualStart(8) },
    { id: "why", from: visualStart(8), to: visualStart(9) },
    { id: "outro", from: visualStart(9), to: timeline.duration + 1 },
  ];
  const RUN = WINDOWS.find((w) => w.id === "run");

  // --- schedule every Band event onto the narration ----------------------------------
  const BEATS = [
    [4, "The owner asks Tofu", (e) => e.room.kind === "hq" && (e.kind === "join" || e.kind === "owner")],
    [4, "Uh oh, coffee runs out", (e) => e.sender === "Tofu"],
    [4, "and mentions Mochi", (e) => e.room.kind === "hq" && e.sender === "Mochi" && (e.kind === "thought" || e.kind === "on-it")],
    [4, "finds three suppliers", (e) => e.kind === "link" || (e.room.kind === "supplier" && (e.kind === "join" || e.kind === "rfq"))],
    [5, "Quotes come back", (e) => e.kind === "quote" || (e.kind === "thought" && /^Got /.test(e.text))],
    [5, "So for each item", (e) => e.kind === "thought" && /Picking winners/.test(e.text)],
    [5, "then haggles", (e) => e.kind === "counter" && e.room.supplier !== "Foxy"],
    [5, "Mochi politely says no", (e) => e.kind === "counter" && e.room.supplier === "Foxy"],
    [6, "The final offers", (e) => e.kind === "final" || e.kind === "budget-ask"],
    [6, "But Yuzu spots", (e) => e.kind === "budget"],
    [6, "so Mochi raises a paw", (e) => e.kind === "attention" || e.kind === "approval-ask"],
    [6, "One reply: approved", (e) => ["approve", "yay", "resolved"].includes(e.kind)],
    [7, "Purchase orders go out", (e) => e.kind === "po"],
    [7, "all three suppliers confirm", (e) => e.kind === "confirm"],
    [7, "every task turns green", (e) => e.kind === "receipt" || e.kind === "logged"],
  ].map(([n, phrase, match]) => ({ at: cue(n, phrase), match, events: [] }));

  let current = 0;
  for (const e of model.events) {
    const j = BEATS.findIndex((b) => b.match(e));
    if (j >= 0) current = j;
    BEATS[j >= 0 ? j : current].events.push(e);
  }
  const showAt = new Map();
  BEATS.forEach((b, j) => {
    const next = j + 1 < BEATS.length ? BEATS[j + 1].at : b.at + 4;
    const stagger = Math.min(0.55, (next - b.at - 0.25) / Math.max(1, b.events.length));
    b.events.forEach((e, i) => showAt.set(e.id, b.at + i * stagger));
  });
  const at = (e) => showAt.get(e.id) ?? Infinity;

  // --- captions ---------------------------------------------------------------------------
  const captions = [];
  for (const s of timeline.scenes) {
    const chunks = s.text.match(/[^.!?…]+[.!?…]+["”]?|[^.!?…]+$/g).map((c) => c.trim());
    const split = [];
    for (const c of chunks) {
      if (c.length <= 74) {
        split.push(c);
        continue;
      }
      const mid = c.length / 2;
      const cut = [...c.matchAll(/[,:;] /g)].map((m) => m.index + 1).sort((a, b) => Math.abs(a - mid) - Math.abs(b - mid))[0];
      if (cut) split.push(c.slice(0, cut).trim(), c.slice(cut).trim());
      else split.push(c);
    }
    let from = 0;
    split.forEach((c, i) => {
      const idx = s.text.indexOf(c, from);
      from = idx + c.length;
      const start = s.start + (idx / s.text.length) * (s.end - s.start);
      const nextIdx = i + 1 < split.length ? s.text.indexOf(split[i + 1], from) : s.text.length;
      const end = s.start + (nextIdx / s.text.length) * (s.end - s.start);
      captions.push({ text: c, start: start - 0.05, end: i + 1 < split.length ? end : s.end + 0.35 });
    });
  }

  // --- DOM ------------------------------------------------------------------------------------
  root.classList.toggle("v2", v2);
  root.innerHTML = `
    <div class="screen">
      <div class="stage onsen-stage"></div>
      <div class="layer title"></div>
      <div class="layer problem"></div>
      <div class="layer herd"></div>
      ${maskyScene ? `<div class="layer masky"></div>` : ""}
      <div class="layer why"></div>
      <div class="layer outro"></div>
      <svg class="spot" viewBox="0 0 1920 1080"><path fill="rgba(42,29,21,.5)" fill-rule="evenodd" d=""/></svg>
      <div class="toast"></div>
      <div class="dim"></div>
    </div>
    ${v2 ? HOST_HTML : ""}
    <div class="caption vcap"></div>`;
  const onsenStage = root.querySelector(".onsen-stage");
  const onsen = new Onsen(onsenStage, model, { badge: "Real Band run" });
  const layers = Object.fromEntries([...root.querySelectorAll(".layer")].map((el) => [el.classList[1], el]));
  const spotPath = root.querySelector(".spot path");
  const spot = root.querySelector(".spot");
  const toast = root.querySelector(".toast");
  const caption = root.querySelector(".vcap");

  const rectOf = (sel) => {
    const el = onsenStage.querySelector(sel);
    let x = 0, y = 0, node = el;
    while (node && node !== onsenStage) {
      x += node.offsetLeft;
      y += node.offsetTop;
      node = node.offsetParent;
    }
    return { x: x - 8, y: y - 8, w: el.offsetWidth + 16, h: el.offsetHeight + 16 };
  };
  const SPOTS = [
    [cue(4, "Tofu puts three tasks"), 2.4, [".tasks"]],
    [cue(4, "opens a quote room"), 2.6, [".col-sup"]],
    [cue(5, "Quotes come back"), 2.4, [".col-sup", ".qbcard"]],
    [cue(5, "Shelly is cheapest"), 4.2, [".qbcard"]],
    [cue(5, "Foxy tries to sneak"), 3.0, [".col-sup .pool:nth-child(3)"]],
    [cue(6, "But Yuzu spots"), 2.8, [".budget"]],
    [cue(7, "every task turns green"), 2.6, [".tasks"]],
  ];
  const TOASTS = [
    [scene(4).start - 0.2, "① Pantry check"],
    [scene(5).start - 0.2, "② Haggling"],
    [scene(6).start - 0.2, "③ Approval"],
    [scene(7).start - 0.2, "④ Orders"],
  ];

  function renderAt(t) {
    for (const w of WINDOWS) {
      const fadeIn = w.from === 0 ? 1 : clamp01((t - w.from) / 0.4);
      const fadeOut = clamp01((w.to - t) / 0.4);
      const o = Math.min(fadeIn, fadeOut);
      const el = w.id === "run" ? onsenStage : layers[w.id];
      el.style.opacity = String(o);
      el.style.display = o > 0 ? "" : "none";
      if (o <= 0) continue;
      const lt = t - w.from;
      if (w.id === "run") {
        onsen.render(t, at, {
          showSlow: t >= cue(5, "Shelly is cheapest"),
          showWin: t >= cue(5, "So for each item"),
        });
      } else if (w.id === "title") renderTitle(layers.title, t, lt);
      else if (w.id === "problem") renderProblem(layers.problem, t);
      else if (w.id === "herd") renderHerd(layers.herd, t);
      else if (w.id === "masky") renderMasky(layers.masky, t);
      else if (w.id === "why") renderWhy(layers.why, t);
      else renderOutro(layers.outro, t);
    }

    // spotlight
    const active = SPOTS.filter(([a, d]) => t >= a - 0.3 && t <= a + d + 0.3);
    if (active.length && t >= RUN.from && t < RUN.to) {
      const [a, d, sels] = active[active.length - 1];
      const o = Math.min(clamp01((t - a + 0.3) / 0.3), clamp01((a + d + 0.3 - t) / 0.3));
      let path = "M0 0H1920V1080H0Z";
      for (const sel of sels) {
        const r = rectOf(sel);
        const rad = 30;
        path += `M${r.x + rad} ${r.y}H${r.x + r.w - rad}Q${r.x + r.w} ${r.y} ${r.x + r.w} ${r.y + rad}V${r.y + r.h - rad}Q${r.x + r.w} ${r.y + r.h} ${r.x + r.w - rad} ${r.y + r.h}H${r.x + rad}Q${r.x} ${r.y + r.h} ${r.x} ${r.y + r.h - rad}V${r.y + rad}Q${r.x} ${r.y} ${r.x + rad} ${r.y}Z`;
      }
      spotPath.setAttribute("d", path);
      spot.style.opacity = String(o);
    } else {
      spot.style.opacity = "0";
    }

    // step toast
    const tst = [...TOASTS].reverse().find(([a]) => t >= a && t < a + 2.6);
    if (tst) {
      const age = t - tst[0];
      toast.style.display = "block";
      toast.textContent = tst[1];
      const k = backOut(age / 0.4);
      const out = clamp01((age - 2.2) / 0.4);
      toast.style.transform = `translateX(-50%) translateY(${(1 - k) * -60 - out * 60}px)`;
      toast.style.opacity = String(1 - out);
    } else {
      toast.style.display = "none";
    }

    const cap = captions.find((c) => t >= c.start && t < c.end);
    caption.style.display = cap ? "" : "none";
    if (cap && caption.textContent !== cap.text) caption.textContent = cap.text;

    if (v2) return renderHost(t);
  }

  // --- v2: Mochi's face-cam -------------------------------------------------------------------
  // The cam shows video/build/v2/host/<frame>.jpg: Mochi's Masky clips laid on the
  // timeline (video/masky_narration.py host). It sits in the side panel, grows over
  // the screen for scene 3.5, and moves center stage while Mochi asks the owner.
  const CAM = {
    slot: { x: 1630, y: 150, s: 220 },
    big: { x: 136, y: 196, s: 620 },
    ask: { x: 790, y: 226, s: 560 },
  };
  const askScene = v2 && scene(6.5);
  const window01 = (t, a, b, ramp = 0.6) => Math.min(clamp01((t - a) / ramp), clamp01((b - t) / ramp));
  const smooth = (x) => x * x * (3 - 2 * x);
  const mix = (a, b, k) => ({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, s: a.s + (b.s - a.s) * k });
  const speaking = (t) => timeline.scenes.some((s) => t >= s.start && t <= s.end);
  const host = v2 && {
    cam: root.querySelector(".cam"),
    tag: root.querySelector(".cam-tag"),
    ask: root.querySelector(".cam-ask"),
    bars: [...root.querySelectorAll(".host-bars i")],
    away: root.querySelector(".host-away"),
    herd: root.querySelector(".host-herd"),
    dim: root.querySelector(".dim"),
  };

  function renderHost(t) {
    const kBig = maskyScene ? smooth(window01(t, scene(3.5).start - 0.75, scene(4).start - 0.75)) : 0;
    const kAsk = askScene ? smooth(window01(t, scene(6.5).start - 0.8, scene(6.6).start - 0.15)) : 0;
    const r = mix(mix(CAM.slot, CAM.big, kBig), CAM.ask, kAsk);
    const away = Math.max(kBig, kAsk);
    host.cam.style.cssText = `left:${r.x}px;top:${r.y}px;width:${r.s}px;height:${r.s}px;border-radius:${(r.s / 2) * (1 - away) + 44 * away}px`;
    host.tag.style.cssText = `left:${r.x + r.s / 2}px;top:${r.y + r.s - 26}px;transform:translateX(-50%) scale(${1 + 0.35 * away})`;
    host.ask.style.cssText = `left:${CAM.ask.x + CAM.ask.s / 2}px;top:${CAM.ask.y - 86}px;opacity:${kAsk};transform:translateX(-50%) translateY(${(1 - kAsk) * 20}px)`;
    host.dim.style.opacity = String(0.55 * kAsk);
    host.away.style.opacity = String(away);
    const talk = speaking(t);
    host.bars.forEach((bar, i) => {
      const h = talk ? 10 + 26 * Math.abs(Math.sin(t * (7 + i * 1.7) + i * 1.3)) : 6;
      bar.style.height = `${h.toFixed(1)}px`;
    });
    host.herd.querySelectorAll("[data-name]").forEach((el, i) => {
      const name = el.dataset.name;
      const html = character(name, { eyes: blinkEyes(name, t), t });
      if (el._html !== html) el.innerHTML = el._html = html;
      el.style.transform = `translateY(${Math.sin(t * 1.4 + i) * 3}px)`;
    });
    const frame = String(Math.max(0, Math.round(t * timeline.fps))).padStart(5, "0");
    const src = `../video/build/v2/host/${frame}.jpg`;
    if (host.cam.getAttribute("src") === src) return undefined;
    host.cam.setAttribute("src", src);
    return host.cam.decode().catch(() => {});
  }

  // --- v2: scene 3.5, Mochi on Masky ------------------------------------------------------
  const MASKY = [
    ["🖼️", "A portrait, made on Masky", "generated from a prompt, then animated", "made Mochi's portrait"],
    ["🎙️", "A Masky voice", "“Expressive Girl”, one of Masky's preset voices", "gave Mochi a voice"],
    ["💬", "Mochi's own personality", "the same persona Mochi's LLM uses on Band", "Mochi's personality"],
    ["🎬", "Lip-synced on camera", "every line in this video, rendered by Masky", "lip-synced"],
  ];
  function buildMasky(el) {
    el.innerHTML = `
      <div class="m-frame"></div>
      <div class="m-title">Mochi, on <span>Masky</span></div>
      <div class="m-list">${MASKY.map(([icon, title, line]) => `<div class="m-row"><div class="m-icon">${icon}</div><div><b>${title}</b><span>${line}</span></div></div>`).join("")}</div>
      <div class="m-api"><span>POST /api/conversations/{id}/turn</span><span>{ "mode": "speak", "output": "video" }</span></div>`;
  }
  function renderMasky(el, t) {
    const title = pop(t, scene(3.5).start - 0.2);
    el.querySelector(".m-title").style.cssText = `opacity:${title.o};transform:scale(${0.8 + 0.2 * title.k})`;
    el.querySelectorAll(".m-row").forEach((row, i) => {
      const p = pop(t, cue(3.5, MASKY[i][3]));
      row.style.cssText = `opacity:${p.o};transform:translateX(${(1 - p.k) * 80}px)`;
    });
    const api = pop(t, cue(3.5, "lip-synced") + 0.6);
    el.querySelector(".m-api").style.cssText = `opacity:${api.o};transform:translateY(${(1 - api.k) * 30}px)`;
  }

  // --- scene builders ------------------------------------------------------------------------

  function springSVG(w, h, waterY) {
    let rocks = "";
    for (let x = 20; x < w; x += 70) {
      rocks += `<ellipse cx="${x}" cy="${waterY - 4 + ((x * 7) % 9)}" rx="${36 + ((x * 13) % 16)}" ry="${22 + ((x * 5) % 8)}" fill="${x % 140 ? "#b9b0a5" : "#a39a90"}" stroke="#7d746b" stroke-width="4"/>`;
    }
    return `<svg class="spring" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs><linearGradient id="sg${h}-${waterY}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a6e2ec"/><stop offset="1" stop-color="#4fb0c6"/></linearGradient></defs>
      <circle cx="${w - 120}" cy="${waterY - 60}" r="90" fill="#7cc483" stroke="#4f9a5a" stroke-width="5"/>
      <circle cx="120" cy="${waterY - 50}" r="80" fill="#8fd296" stroke="#4f9a5a" stroke-width="5"/>
      <rect x="0" y="${waterY}" width="${w}" height="${h - waterY}" fill="url(#sg${h}-${waterY})"/>${rocks}</svg>`;
  }

  function frontWater(w, h, base, t, amp = 6) {
    let d = `M0 ${h} L0 ${base}`;
    for (let x = 0; x <= w; x += 16) d += ` L${x} ${(base + amp * Math.sin(x / 60 + t * 1.6) + amp * 0.5 * Math.sin(x / 27 - t)).toFixed(1)}`;
    return `<path d="${d} L${w} ${h} Z" fill="#6cc3d6" opacity=".94"/>`;
  }

  function steamSVG(w, base, t, n) {
    let out = "";
    for (let i = 0; i < n; i++) {
      const p = ((t + i * 1.3) % 4) / 4;
      const x = ((i + 0.5) / n) * w + Math.sin(t * 0.6 + i) * 18;
      out += `<path d="M${x} ${base - p * 140} q-14 -22 0 -44 q14 -22 0 -44" fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round" opacity="${(Math.sin(p * Math.PI) * 0.6).toFixed(3)}"/>`;
    }
    return out;
  }

  function yuzuSVG(x, y, r) {
    return `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})"><circle r="${r}" fill="#ffb627" stroke="#c47a00" stroke-width="3"/><ellipse cx="${-r * 0.35}" cy="${-r * 0.35}" rx="${r * 0.3}" ry="${r * 0.2}" fill="#fff" opacity=".55"/><path d="M0 ${-r} q${r * 0.6} ${-r * 0.6} ${r * 1.1} ${-r * 0.2} q${-r * 0.6} ${r * 0.5} ${-r * 1.1} ${r * 0.2}z" fill="#6cc070"/></g>`;
  }

  function buildTitle(el) {
    el.innerHTML = `
      <div class="t-title"><span class="capy">Capy</span><span class="bar">Bargain</span></div>
      <div class="t-sub">A purchasing department run by AI capybaras · built on <b>Band</b>${v2 ? " · voiced on <b>Masky</b>" : ""}</div>
      <div class="t-pool">${springSVG(1920, 600, 200)}<div class="t-mochi"></div><svg class="t-front" viewBox="0 0 1920 600" preserveAspectRatio="none"></svg></div>
      <div class="t-sign">☕ Capy Café</div>
      <div class="t-tag">Mochi 🍊 <em>head buyer</em></div>`;
  }
  function renderTitle(el, t) {
    const title = el.querySelector(".t-title");
    const p = pop(t, 0.15, 0.6);
    title.style.transform = `translateX(-50%) scale(${0.6 + 0.4 * p.k})`;
    title.style.opacity = p.o;
    const sub = el.querySelector(".t-sub");
    sub.style.opacity = clamp01((t - 0.9) / 0.5);
    sub.style.transform = `translateX(-50%) translateY(${(1 - easeOut((t - 0.9) / 0.5)) * 20}px)`;
    const mochi = el.querySelector(".t-mochi");
    const html = character("Mochi", { eyes: blinkEyes("Mochi", t, t > cue(1, "and Mochi runs") ? "happy" : "open") });
    if (mochi._html !== html) mochi.innerHTML = mochi._html = html;
    mochi.style.transform = `translateX(-50%) translateY(${Math.sin(t * 1.4) * 6}px)`;
    let front = steamSVG(1920, 250, t, 7) + frontWater(1920, 600, 430, t);
    [440, 620, 1300, 1480, 1660, 260].forEach((x, i) => (front += yuzuSVG(x + Math.sin(t * 0.5 + i) * 12, 456 + Math.sin(t * 1.4 + i) * 4, 22)));
    el.querySelector(".t-front").innerHTML = front;
    const tag = pop(t, cue(1, "This is Mochi"));
    el.querySelector(".t-tag").style.cssText = `opacity:${tag.o};transform:rotate(4deg) scale(${tag.k})`;
    const sign = pop(t, cue(1, "runs purchasing"));
    el.querySelector(".t-sign").style.cssText = `opacity:${sign.o};transform:rotate(-6deg) scale(${sign.k})`;
  }

  function buildProblem(el) {
    el.innerHTML = `
      <div class="p-title">Small cafés overpay for supplies 😩</div>
      <div class="p-cards">
        <div class="p-card"><div class="big">📞</div><b>Phone tag</b><span>"I'll call you back with a price…"</span></div>
        <div class="p-card"><div class="big">📧</div><b>Email ping-pong</b><span>Re: Re: Re: quote request</span></div>
        <div class="p-card"><div class="big">📊</div><b>Spreadsheets</b><span>Comparing prices by hand</span></div>
      </div>
      <div class="p-same"><div class="p-tofu"></div><div><b>🔁 Same supplier · same price · every week</b><span>so most owners never compare at all</span></div></div>`;
  }
  function renderProblem(el, t) {
    const title = pop(t, scene(2).start - 0.2);
    el.querySelector(".p-title").style.cssText = `opacity:${title.o};transform:translateX(-50%) scale(${0.8 + 0.2 * title.k})`;
    const cues = [cue(2, "phone tag"), cue(2, "emails"), cue(2, "spreadsheets")];
    el.querySelectorAll(".p-card").forEach((card, i) => {
      const p = pop(t, cues[i]);
      const wob = Math.sin(t * 3 + i) * 2;
      card.style.cssText = `opacity:${p.o};transform:translateY(${(1 - p.k) * 60}px) rotate(${wob}deg) scale(${0.85 + 0.15 * p.k})`;
    });
    const same = pop(t, cue(2, "so most owners"));
    el.querySelector(".p-same").style.cssText = `opacity:${same.o};transform:translateX(-50%) scale(${0.85 + 0.15 * same.k})`;
    const tofu = el.querySelector(".p-tofu");
    const html = character("Tofu", { eyes: "sleepy" });
    if (tofu._html !== html) tofu.innerHTML = tofu._html = html;
  }

  const HERD = [
    ["Tofu", "Pantry keeper", "Counts the shelves every morning", "Tofu counts the pantry"],
    ["Yuzu", "Treasurer", "Guards the weekly budget", "Yuzu guards the budget"],
    ["Mochi", "Head buyer", "Finds suppliers and haggles politely", "Mochi does the haggling"],
    ["Shelly", "Slow & Steady Farm", "Cheapest prices, but takes 4 days", "Shelly the tortoise"],
    ["Zippy", "Zippy Express Pantry", "Premium prices · next-day delivery", "Zippy the hummingbird"],
    ["Foxy", "Foxy Wholesale", "Delivers in 2 days · loves an upsell", "Foxy the fox"],
  ];
  function buildHerd(el) {
    const card = ([name, role, line]) =>
      `<div class="h-card" data-name="${name}"><div class="h-pic"></div><div class="h-name">${name} ${CAST[name].emoji}</div><div class="h-role">${role}</div><div class="h-line">${line}</div></div>`;
    el.innerHTML = `
      <div class="h-title">Meet the herd <span>· 6 AI agents on Band</span></div>
      <div class="h-row-label r1">☕ Capy Café staff</div>
      <div class="h-row r1">${HERD.slice(0, 3).map(card).join("")}</div>
      <div class="h-row-label r2">🛒 Suppliers · each one its own agent</div>
      <div class="h-row r2">${HERD.slice(3).map(card).join("")}</div>
      <div class="h-banner">Capybaras get along with everyone 💛</div>
      <div class="h-hearts"></div>`;
  }
  function renderHerd(el, t) {
    const title = pop(t, scene(3).start - 0.2);
    el.querySelector(".h-title").style.cssText = `opacity:${title.o};transform:translateX(-50%) scale(${0.8 + 0.2 * title.k})`;
    el.querySelectorAll(".h-row-label").forEach((lab, i) => {
      const p = pop(t, cue(3, i ? "The suppliers are agents" : "Tofu counts") - 0.3);
      lab.style.opacity = p.o;
    });
    const friends = cue(3, "Capybaras get along");
    el.querySelectorAll(".h-card").forEach((card, i) => {
      const [name, , , phrase] = HERD[i];
      const p = pop(t, cue(3, phrase));
      card.style.opacity = p.o;
      card.style.transform = `translateY(${(1 - p.k) * 70 + Math.sin(t * 1.5 + i) * 3}px) scale(${0.8 + 0.2 * p.k})`;
      const eyes = blinkEyes(name, t, t > friends ? "happy" : name === "Shelly" ? "sleepy" : "open");
      const pic = card.querySelector(".h-pic");
      const html = character(name, { eyes, t });
      if (pic._html !== html) pic.innerHTML = pic._html = html;
    });
    const banner = pop(t, friends);
    el.querySelector(".h-banner").style.cssText = `opacity:${banner.o};transform:translateX(-50%) scale(${0.7 + 0.3 * banner.k})`;
    let hearts = "";
    if (t > friends) {
      for (let i = 0; i < 16; i++) {
        const age = t - friends - i * 0.12;
        if (age < 0) continue;
        const x = 260 + ((i * 397) % 1400);
        const y = 900 - age * 160;
        hearts += `<span style="left:${x + Math.sin(age * 3 + i) * 20}px;top:${y}px;opacity:${clamp01(1.4 - age / 3)}">${i % 3 ? "💛" : "🧡"}</span>`;
      }
    }
    el.querySelector(".h-hearts").innerHTML = hearts;
  }

  const WHY = [
    ["@", "@mentions route the work", "Only the agent you mention wakes up. Everyone else keeps soaking ♨️", "Mentions route the work"],
    ["🔎", "Peer lookup finds suppliers", "band_lookup_peers → Shelly 🐢 Zippy 🐦 Foxy 🦊, no hard-coded wiring", "peer lookup finds suppliers"],
    ["📌", "The task board tracks progress", "Tofu creates the tasks, Mochi claims and completes them", "the task board tracks"],
    ["✋", "Attention events keep a human in charge", "Over budget? Mochi raises a paw and waits for the owner", "attention events keep"],
    ["🤝", "Contacts connect other companies", "Each supplier can live in its own Band account, linked by a contact request", "And each supplier could live"],
  ];
  function buildWhy(el) {
    el.innerHTML = `
      <div class="w-title">Every step is a real Band message</div>
      <div class="w-grid">${WHY.map(([icon, title, line]) => `<div class="w-tile"><div class="w-icon">${icon}</div><div><b>${title}</b><span>${line}</span></div></div>`).join("")}</div>
      <div class="w-stats"><span>6 agents</span><span>4 rooms</span><span>${model.events.length} Band events</span><span>1 human approval</span>${v2 ? "<span>🎭 voiced on Masky</span>" : ""}</div>
      <div class="w-mochi"></div>`;
  }
  function renderWhy(el, t) {
    const title = pop(t, scene(8).start - 0.2);
    el.querySelector(".w-title").style.cssText = `opacity:${title.o};transform:translateX(-50%) scale(${0.8 + 0.2 * title.k})`;
    el.querySelectorAll(".w-tile").forEach((tile, i) => {
      const p = pop(t, cue(8, WHY[i][3]));
      tile.style.cssText = `opacity:${p.o};transform:translateX(${(1 - p.k) * -80}px)`;
    });
    el.querySelector(".w-stats").style.opacity = clamp01((t - scene(8).start - 1) / 0.5);
    const m = el.querySelector(".w-mochi");
    const html = character("Mochi", { eyes: blinkEyes("Mochi", t, "happy") });
    if (m._html !== html) m.innerHTML = m._html = html;
    m.style.transform = `translateY(${Math.sin(t * 1.5) * 6}px) rotate(${Math.sin(t * 0.8) * 3}deg)`;
  }

  const OUTRO_CAST = ["Owner", "Tofu", "Yuzu", "Mochi", "Shelly", "Zippy", "Foxy"];
  const receipt = model.events.find((e) => e.kind === "receipt")?.text ?? "";
  const receiptTotal = receipt.match(/\*\*Total (\$[0-9,.]+)\*\*/)?.[1] ?? "";
  const receiptSaved = receipt.match(/saved \*\*(\$[0-9,.]+)\*\*/)?.[1] ?? "";
  function buildOutro(el) {
    el.innerHTML = `
      <div class="o-title"><span class="capy">Capy</span><span class="bar">Bargain</span></div>
      <div class="o-line">Capybaras are friends with everyone… even your suppliers! 💛</div>
      <div class="o-stats"><span>🧾 ${receiptTotal} restocked</span><span>💰 ${receiptSaved} saved</span><span>⏱️ ${Math.round(model.duration)}-second run</span><span>🍊 6 agents on Band</span></div>
      <div class="o-pool">${springSVG(1920, 620, 170)}${OUTRO_CAST.map((n) => `<div class="o-who" data-name="${n}"></div>`).join("")}<svg class="o-front" viewBox="0 0 1920 620" preserveAspectRatio="none"></svg></div>
      <div class="o-foot">github.com/chinesepowered/hack-band${v2 ? " · faces &amp; voices by Masky" : ""}</div>`;
  }
  function renderOutro(el, t) {
    const s = scene(9).start;
    const title = pop(t, s - 0.3, 0.6);
    el.querySelector(".o-title").style.cssText = `opacity:${title.o};transform:translateX(-50%) scale(${0.6 + 0.4 * title.k})`;
    const line = pop(t, cue(9, "Capybaras are friends"));
    el.querySelector(".o-line").style.cssText = `opacity:${line.o};transform:translateX(-50%) translateY(${(1 - line.k) * 20}px)`;
    el.querySelector(".o-stats").style.opacity = clamp01((t - s - 0.6) / 0.5);
    el.querySelector(".o-foot").style.opacity = clamp01((t - s - 1.2) / 0.5);
    el.querySelectorAll(".o-who").forEach((w, i) => {
      const name = w.dataset.name;
      const html = character(name, { eyes: blinkEyes(name, t, "happy"), t });
      if (w._html !== html) w.innerHTML = w._html = html;
      const x = 210 + i * 250;
      w.style.left = `${x - 131}px`;
      w.style.transform = `translateY(${Math.sin(t * 1.3 + i * 1.1) * 6}px)`;
    });
    let front = steamSVG(1920, 240, t, 8) + frontWater(1920, 620, 440, t);
    [335, 585, 835, 1085, 1335, 1585].forEach((x, i) => (front += yuzuSVG(x + Math.sin(t * 0.5 + i) * 10, 466 + Math.sin(t * 1.4 + i) * 4, 20)));
    el.querySelector(".o-front").innerHTML = front;
  }

  buildTitle(layers.title);
  buildProblem(layers.problem);
  buildHerd(layers.herd);
  if (maskyScene) buildMasky(layers.masky);
  buildWhy(layers.why);
  buildOutro(layers.outro);

  return { renderAt, duration: timeline.duration, fps: timeline.fps };
}
