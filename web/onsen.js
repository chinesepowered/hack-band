// The Capy Onsen: every Band room is a hot spring. render(t) is a pure
// function of time, so the same code drives the browser replay, the live view
// and frame-by-frame video capture.

import { CAST, blinkEyes, character } from "./art.js";
import { budgetState, dollars, fmt, inline, markdown, parseTable, quoteBoard, splitTable, taskStates } from "./model.js";

const SUPPLIER_ORDER = ["Shelly", "Zippy", "Foxy"];
const ITEM_ICON = { "coffee beans": "☕", "oat milk": "🥛", flour: "🌾" };

const set = (el, html) => {
  if (el._html !== html) {
    el.innerHTML = html;
    el._html = html;
    return true;
  }
  return false;
};
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const easeOut = (x) => 1 - Math.pow(1 - clamp01(x), 3);
const backOut = (x) => {
  x = clamp01(x);
  const c = 1.9;
  return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2);
};
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function poolSVG(w, h, waterY) {
  const r = rng(w * 7 + h);
  const rocks = [];
  for (let x = 10; x < w; x += 34 + r() * 26) {
    const ry = 13 + r() * 7;
    rocks.push(`<ellipse cx="${x}" cy="${waterY - 6 + r() * 6}" rx="${20 + r() * 12}" ry="${ry}" fill="${r() > 0.5 ? "#b9b0a5" : "#a39a90"}" stroke="#7d746b" stroke-width="2.5"/>`);
  }
  const bushes = [
    `<circle cx="${w - 38}" cy="${waterY - 30}" r="${h * 0.17}" fill="#7cc483" stroke="#4f9a5a" stroke-width="3"/>`,
    `<circle cx="${w - 74}" cy="${waterY - 18}" r="${h * 0.12}" fill="#8fd296" stroke="#4f9a5a" stroke-width="3"/>`,
    `<circle cx="${w - 92}" cy="${waterY - 38}" r="4" fill="#ffb627"/>`,
    `<circle cx="${w - 30}" cy="${waterY - 56}" r="4" fill="#ffb627"/>`,
  ];
  return `<svg class="bg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="wg${w}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#a6e2ec"/><stop offset="1" stop-color="#5cb9cf"/></linearGradient></defs>
    ${bushes.join("")}
    <rect x="0" y="${waterY}" width="${w}" height="${h - waterY}" fill="url(#wg${w})"/>
    ${rocks.join("")}
  </svg>`;
}

function waveFront(w, h, base, t, amp) {
  let d = `M0 ${h} L0 ${base}`;
  for (let x = 0; x <= w; x += 12) {
    const y = base + amp * Math.sin(x / 34 + t * 1.7) + amp * 0.6 * Math.sin(x / 17 - t * 1.15);
    d += ` L${x} ${y.toFixed(1)}`;
  }
  d += ` L${w} ${h} Z`;
  let crest = "";
  for (let x = 0; x <= w; x += 12) {
    const y = base + amp * Math.sin(x / 34 + t * 1.7) + amp * 0.6 * Math.sin(x / 17 - t * 1.15);
    crest += `${x === 0 ? "M" : "L"}${x} ${y.toFixed(1)} `;
  }
  return { d, crest };
}

function steam(w, base, t, n, scale) {
  let out = "";
  for (let i = 0; i < n; i++) {
    const period = 3.6 + (i % 3) * 0.7;
    const p = ((t + i * 1.37) % period) / period;
    const x = ((i + 0.5) / n) * w + Math.sin(t * 0.7 + i) * 10;
    const y = base - p * 70 * scale;
    const op = Math.sin(p * Math.PI) * 0.55;
    out += `<path d="M${x.toFixed(1)} ${y.toFixed(1)} q${-7 * scale} ${-11 * scale} 0 ${-22 * scale} q${7 * scale} ${-11 * scale} 0 ${-22 * scale}"
      fill="none" stroke="#fff" stroke-width="${5 * scale}" stroke-linecap="round" opacity="${op.toFixed(3)}"/>`;
  }
  return out;
}

function floaties(pool, t) {
  const hq = pool.kind === "hq";
  const size = hq ? 10 : 6.5;
  const y0 = pool.waterY + (hq ? 40 : 20);
  const xs = [];
  for (let i = 0; i + 1 < pool.xs.length; i++) xs.push((pool.xs[i] + pool.xs[i + 1]) / 2);
  xs.push(pool.xs[0] - (hq ? 80 : 60), pool.xs[pool.xs.length - 1] + (hq ? 86 : 66));
  let out = "";
  xs.forEach((x0, i) => {
    const x = x0 + Math.sin(t * 0.4 + i * 2) * 8;
    const y = y0 + Math.sin(t * 1.5 + i) * 3;
    out += `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
      <circle r="${size}" fill="#ffb627" stroke="#c47a00" stroke-width="2.2"/>
      <ellipse cx="${-size * 0.35}" cy="${-size * 0.35}" rx="${size * 0.3}" ry="${size * 0.2}" fill="#fff" opacity=".55"/>
      <path d="M0 ${-size} q${size * 0.6} ${-size * 0.6} ${size * 1.1} ${-size * 0.2} q${-size * 0.6} ${size * 0.5} ${-size * 1.1} ${size * 0.2}z" fill="#6cc070"/>
    </g>`;
  });
  return out;
}

const SHORT_ROLE = { Owner: "human", Tofu: "pantry", Mochi: "buyer", Yuzu: "budget" };

const avatar = (name) => `<div class="av">${character(name === "Owner" ? "Owner" : name, { t: 0 })}</div>`;
const nameLine = (name, extra = "") =>
  `<div class="meta"><b>${name}</b> ${CAST[name]?.emoji ?? ""} ${extra}</div>`;

// The agent's own line (the first paragraph), kept short for the small pools.
function voiceOf(text) {
  const first = text.split("\n\n")[0].trim();
  const clean = first.startsWith("|") ? "" : first;
  return clean.length > 150 ? clean.slice(0, clean.lastIndexOf(" ", 146)) + "…" : clean;
}

function compactChips(e) {
  const table = parseTable(e.text);
  const { after } = splitTable(e.text);
  const lead = `<p>${inline(voiceOf(e.text))}</p>`;
  if (!table) {
    if (e.kind === "confirm") {
      const arriving = e.text.match(/arriving \**([^*\n]+?)\**(?:\.|$|\n)/)?.[1];
      return lead + (arriving ? `<p><span class="chip">📦 confirmed · arriving ${inline(arriving)}</span></p>` : "");
    }
    return `<p>${inline(e.text.replace(/\n/g, " "))}</p>`;
  }
  const rows = table.rows;
  let chips = "";
  switch (e.kind) {
    case "rfq":
      chips = `<span class="chip">🛒 ${rows.map((r) => `${r.item} ${r.qty}`).join(" · ")}</span>`;
      break;
    case "quote": {
      const total = after.match(/Total: \$([0-9,.]+)/)?.[1];
      const d = after.match(/delivery in \**(\d+ days?)/)?.[1];
      chips = `<span class="chip">🧾 total $${total}</span><span class="chip">🚚 ${d}</span>`;
      if (/psst/i.test(after)) chips += `<span class="chip honey">🍯 Psst… Honey Bundle $36?</span>`;
      break;
    }
    case "counter":
      chips = rows.map((r) => `<span class="chip">🙏 ${r.item}: <s>${r["your price"]}</s> → ${r["could you do"]}?</span>`).join("");
      if (/no honey/i.test(e.text)) chips += `<span class="chip honey">🍯 no honey, thanks</span>`;
      break;
    case "final":
      chips =
        rows.map((r) => `<span class="chip">✨ ${r.item} ${r["unit price"]}</span>`).join("") +
        `<span class="chip">total $${after.match(/Total: \$([0-9,.]+)/)?.[1]}</span>`;
      break;
    case "po":
      chips = `<span class="chip">📄 ${rows.map((r) => `${r.item} × ${r.qty}`).join(", ")} · ${after.match(/Total (\$[0-9,.]+)/)?.[1] ?? ""}</span>`;
      break;
    default:
      return markdown(e.text);
  }
  return lead + `<p>${chips}</p>`;
}

function bubbleHTML(e, compact) {
  const cls = e.sender === "Owner" ? "owner" : (e.sender || "").toLowerCase();
  const content = compact ? compactChips(e) : markdown(e.text);
  return `<div class="msg" data-id="${e.id}">${avatar(e.sender)}<div class="body">${nameLine(
    e.sender === "Owner" ? "Owner" : e.sender,
    e.sender === "Owner" ? "· human" : ""
  )}<div class="bubble ${cls}">${content}</div></div></div>`;
}

function feedItem(e, compact) {
  switch (e.kind) {
    case "join":
      return compact ? "" : `<div class="sys" data-id="${e.id}">🫧 ${e.sender} hopped into the pool</div>`;
    case "link":
      return `<div class="sys" data-id="${e.id}">📌 ${inline(e.text)}</div>`;
    case "thought":
      return compact ? "" : `<div class="thought" data-id="${e.id}">💭 ${inline(e.text)}</div>`;
    case "attention":
      return `<div class="attn" data-id="${e.id}"><span class="paw">✋</span><div><small>Mochi raised a paw · needs the owner</small>${inline(e.text)}</div></div>`;
    case "resolved":
      return `<div class="sys" data-id="${e.id}">✅ ${inline(e.text)}</div>`;
    default:
      return bubbleHTML(e, compact);
  }
}

export class Onsen {
  constructor(stage, model, { badge = "Replay of a real Band run" } = {}) {
    this.stage = stage;
    this.model = model;
    this.hq = model.rooms.find((r) => r.kind === "hq");
    this.sups = SUPPLIER_ORDER.map((n) => model.rooms.find((r) => r.supplier === n)).filter(Boolean);
    const messages = model.events.filter((e) => e.type === "text").length;

    stage.innerHTML = `
      <div class="topbar">
        <div class="logo">${character("Mochi", { eyes: "happy" })}</div>
        <div><div class="wordmark">Capy<span>Bargain</span></div>
          <div class="tagline">Capy Café's purchasing department, run by AI agents on Band</div></div>
        <div class="spacer"></div>
        <div class="badge live"><span class="dot"></span>${badge} · <span class="clock"></span></div>
        <div class="badge"><span class="band">Band</span> ${model.rooms.length} rooms · ${messages} messages · 6 agents</div>
      </div>
      <div class="col col-hq"></div>
      <div class="col col-sup"></div>
      <div class="col col-boards">
        <div class="card board qbcard"></div>
        <div class="card board tasks"></div>
        <div class="card board budget"></div>
      </div>
      <div class="confetti"></div>
      <div class="caption" style="display:none"></div>`;

    this.clock = stage.querySelector(".clock");
    this.caption = stage.querySelector(".caption");
    this.confetti = stage.querySelector(".confetti");
    this.qbEl = stage.querySelector(".qbcard");
    this.tasksEl = stage.querySelector(".tasks");
    this.budgetEl = stage.querySelector(".budget");

    this.pools = [];
    this.pools.push(this.makePool(stage.querySelector(".col-hq"), this.hq, "hq", ["Owner", "Tofu", "Mochi", "Yuzu"]));
    for (const r of this.sups) {
      this.pools.push(this.makePool(stage.querySelector(".col-sup"), r, "sup", ["Mochi", r.supplier]));
    }
  }

  makePool(col, room, kind, cast) {
    const W = kind === "hq" ? 756 : 544;
    const H = kind === "hq" ? 286 : 118;
    const waterY = kind === "hq" ? 200 : 78;
    const el = document.createElement("div");
    el.className = `card pool ${kind}`;
    const title = room.title.replace("×", "<small>×</small>");
    el.innerHTML = `<div class="scene">${poolSVG(W, H, waterY)}<div class="sign">${title}</div><svg class="front" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"></svg></div><div class="feed"></div>`;
    if (kind === "hq") el.querySelector(".scene").insertAdjacentHTML("beforeend", `<div class="approval" style="display:none"></div>`);
    col.appendChild(el);
    const scene = el.querySelector(".scene");
    const size = kind === "hq" ? 150 : 92;
    const xs = kind === "hq" ? [118, 288, 458, 628] : [312, 446];
    const whos = cast.map((name, i) => {
      const w = document.createElement("div");
      w.className = "who";
      w.style.width = `${size}px`;
      w.style.left = `${xs[i] - size / 2}px`;
      w.innerHTML = `<div class="char"></div><div class="think" style="display:none"></div><div class="typing" style="display:none">•••</div>`;
      scene.insertBefore(w, scene.querySelector("svg.front"));
      const tag = document.createElement("div");
      tag.className = "nametag";
      tag.style.left = `${xs[i]}px`;
      tag.innerHTML = `${name}${kind === "hq" ? ` <em>${SHORT_ROLE[name]}</em>` : ""}`;
      scene.appendChild(tag);
      return { name, el: w, char: w.querySelector(".char"), think: w.querySelector(".think"), typing: w.querySelector(".typing"), phase: i * 1.7 };
    });
    return {
      room, kind, el, W, H, waterY, whos, xs,
      front: el.querySelector("svg.front"),
      feed: el.querySelector(".feed"),
      approval: el.querySelector(".approval"),
    };
  }

  // t: seconds on the display clock. at(e): when event e appears (Infinity = not yet).
  render(t, at, opts = {}) {
    const shown = (e) => at(e) <= t;
    const visible = this.model.events.filter(shown);
    const realNow = visible.length ? Math.max(...visible.map((e) => e.ts)) : -1;
    this.clock.textContent = `${fmtClock(Math.max(0, realNow))} / ${fmtClock(this.model.duration)}`;

    for (const pool of this.pools) this.renderPool(pool, t, at, shown);
    this.renderQuoteBoard(shown, opts);
    this.renderTasks(realNow);
    this.renderBudget(shown);
    this.renderApproval(t, at, shown);
    this.renderConfetti(t, at);

    if (opts.caption) {
      this.caption.style.display = "";
      set(this.caption, opts.caption);
    } else {
      this.caption.style.display = "none";
    }
  }

  renderPool(pool, t, at, shown) {
    const compact = pool.kind === "sup";
    const roomEvents = this.model.events.filter((e) => e.room.id === pool.room.id);
    const vis = roomEvents.filter(shown);
    const limit = compact ? 3 : 9;
    const html = vis.slice(-limit).map((e) => feedItem(e, compact)).join("");
    set(pool.feed, html);
    for (const node of pool.feed.querySelectorAll("[data-id]")) {
      const e = roomEvents.find((x) => x.id === node.dataset.id);
      const age = t - at(e);
      if (age < 0.6) {
        const k = backOut(age / 0.45);
        node.style.transform = `translateY(${(1 - easeOut(age / 0.4)) * 18}px) scale(${0.92 + 0.08 * k})`;
        node.style.opacity = String(clamp01(age / 0.25));
      } else if (node.style.transform) {
        node.style.transform = "";
        node.style.opacity = "";
      }
    }

    // characters
    const done = this.model.events.some((e) => e.kind === "receipt" && shown(e));
    const approved = this.model.events.some((e) => e.kind === "approve" && shown(e));
    for (const who of pool.whos) {
      const mine = roomEvents.filter((e) => e.sender === who.name && e.type === "text");
      const last = [...mine].reverse().find(shown);
      const speakAge = last ? t - at(last) : 99;
      const next = mine.find((e) => !shown(e) && at(e) - t < 0.9);
      const thought = [...roomEvents].reverse().find((e) => e.sender === who.name && e.kind === "thought" && shown(e) && t - at(e) < 1.6);
      let eyes = "open";
      if (who.name === "Shelly") eyes = "sleepy";
      const confirmed = this.model.events.some((e) => e.kind === "confirm" && e.sender === who.name && shown(e));
      if ((who.name === "Mochi" && done) || (who.name === "Owner" && approved) || confirmed) eyes = "happy";
      if (speakAge < 0.8) eyes = "happy";
      eyes = blinkEyes(who.name, t, eyes);
      set(who.char, character(who.name, { eyes, t: who.name === "Zippy" || who.name === "Owner" ? t : 0 }));
      const bob = Math.sin(t * 1.3 + who.phase) * (pool.kind === "hq" ? 3 : 2);
      const lift = speakAge < 1.2 ? -Math.sin(clamp01(speakAge / 1.2) * Math.PI) * (pool.kind === "hq" ? 16 : 9) : 0;
      const base = pool.kind === "hq" ? -14 : -2;
      who.el.style.transform = `translateY(${(base + bob + lift).toFixed(2)}px)`;
      who.typing.style.display = next ? "" : "none";
      if (next) who.typing.textContent = ["•  ", "•• ", "•••"][Math.floor(t * 5) % 3];
      who.think.style.display = thought ? "" : "none";
      if (thought) who.think.textContent = "💭";
    }

    // water, steam, floating yuzus
    const amp = pool.kind === "hq" ? 3.2 : 2;
    const { d, crest } = waveFront(pool.W, pool.H, pool.waterY + (pool.kind === "hq" ? 22 : 12), t, amp);
    pool.front.innerHTML = `
      ${steam(pool.W - 120, pool.waterY + 10, t, pool.kind === "hq" ? 6 : 3, pool.kind === "hq" ? 1 : 0.55)}
      <path d="${d}" fill="#6cc3d6" opacity=".93"/>
      <path d="${crest}" fill="none" stroke="#e9fbff" stroke-width="3" opacity=".8"/>
      ${floaties(pool, t)}`;
  }

  renderQuoteBoard(shown, opts) {
    const qb = quoteBoard(this.model, shown);
    const showSlow = opts.showSlow ?? qb.picked;
    const showWin = opts.showWin ?? qb.picked;
    let html = `<h2>🧾 Quote board <small>unit prices</small></h2>`;
    if (!qb.items.length) {
      set(this.qbEl, html + `<div class="empty">Waiting for Tofu's pantry check…</div>`);
      return;
    }
    html += `<table class="qb"><tr><th></th>${qb.cols
      .map((c) => `<th><span class="sup">${CAST[c.name].emoji} ${c.name}</span>${c.days ? `🚚 ${c.days} day${c.days > 1 ? "s" : ""}` : "…"}</th>`)
      .join("")}</tr>`;
    for (const it of qb.items) {
      html += `<tr><td class="item">${ITEM_ICON[it.item] ?? "📦"} ${it.item}<small>${it.order} · runs out in ${it.deadline}d</small></td>`;
      for (const c of qb.cols) {
        const p = c.prices[it.item];
        if (p == null) {
          html += `<td class="wait">${c.quoted ? "–" : "…"}</td>`;
          continue;
        }
        const slow = showSlow && c.days > it.deadline;
        const win = showWin && qb.winners[it.item] === c.name;
        const fin = c.finals[it.item];
        const price = fin != null && win ? `<s>${fmt(p)}</s>${fmt(fin)}` : fmt(p);
        const tag = slow ? `<span class="tag">🐌 too slow</span>` : "";
        html += `<td class="${slow ? "slow" : ""} ${win ? "win" : ""}">${price}${tag}${win ? `<span class="crown">${c.confirmed ? "✅" : "🍊"}</span>` : ""}</td>`;
      }
      html += `</tr>`;
    }
    html += `</table>`;
    const finals = qb.cols.filter((c) => Object.keys(c.finals).length);
    if (finals.length === qb.cols.length) {
      const total = finals.reduce((s, c) => s + Object.entries(c.finals).reduce((a, [item, price]) => a + price * dollars(qb.items.find((i) => i.item === item).order), 0), 0);
      html += `<div class="qb-foot"><span>Best on-time deal</span><b>${fmt(total)}</b></div>`;
    } else if (qb.cols.every((c) => c.quoted)) {
      html += `<div class="qb-foot"><span>All 3 quotes in</span><span>haggling…</span></div>`;
    } else {
      html += `<div class="qb-foot"><span>Waiting for quotes…</span><span>${qb.cols.filter((c) => c.quoted).length}/${qb.cols.length}</span></div>`;
    }
    set(this.qbEl, html);
  }

  renderTasks(realNow) {
    const tasks = taskStates(this.model, realNow).filter((t) => t.created);
    const label = { pending: "to do", in_progress: "haggling…", in_review: "needs OK", completed: "done ✓" };
    let html = `<h2>📌 Task board <small>Band room board</small></h2>`;
    if (!tasks.length) {
      html += `<div class="empty">No tasks yet</div>`;
    } else {
      html += `<div class="goal">🎯 ${this.model.goal}</div>`;
      for (const task of tasks) {
        const [what, qty] = task.subject.replace("Restock ", "").split(" · ");
        const sub = task.comment ? task.comment.replace(/ · /g, " · ") : qty;
        html += `<div class="task"><span class="num">#${task.number}</span><span class="subj">${ITEM_ICON[what] ?? ""} ${what}<small>${sub}</small></span><span class="pill ${task.status}">${label[task.status] ?? task.status}</span></div>`;
      }
    }
    set(this.tasksEl, html);
  }

  renderBudget(shown) {
    const b = budgetState(this.model, shown);
    let html = `<h2>🪙 Weekly budget <small>checked by Yuzu</small></h2>`;
    if (!b) {
      set(this.budgetEl, html + `<div class="empty">Yuzu checks before anything is ordered</div>`);
      return;
    }
    const scale = (v) => `${(v / (b.budget * 1.08)) * 100}%`;
    html += `<div class="bar">
        <div class="seg spent" style="left:0;width:${scale(b.spent)}"></div>
        <div class="seg order" style="left:${scale(b.spent)};width:${scale(b.order - b.over)}"></div>
        ${b.over ? `<div class="seg over" style="left:${scale(b.budget)};width:${scale(b.over)}"></div>` : ""}
        <div class="limit" style="left:${scale(b.budget)}"><span>${fmt(b.budget)}</span></div>
      </div>
      <div class="legend"><span>spent ${fmt(b.spent)}</span><span>this order ${fmt(b.order)}</span></div>
      <div class="verdict ${b.approved ? "ok" : "warn"}">${b.approved ? `✅ ${fmt(b.over)} over, approved by the owner` : `⚠️ ${fmt(b.over)} over budget → needs the owner's OK`}</div>
      ${b.saved ? `<div class="saved">Saved <b>${fmt(b.saved)}</b> vs last month</div>` : ""}`;
    set(this.budgetEl, html);
  }

  renderApproval(t, at, shown) {
    const pool = this.pools[0];
    const attn = this.model.events.find((e) => e.kind === "attention");
    const approve = this.model.events.find((e) => e.kind === "approve");
    if (!attn || !shown(attn) || (approve && shown(approve) && t - at(approve) > 2.6)) {
      pool.approval.style.display = "none";
      return;
    }
    pool.approval.style.display = "";
    const age = t - at(attn);
    const k = backOut(age / 0.5);
    const out = approve && shown(approve) ? clamp01((t - at(approve) - 2.1) / 0.5) : 0;
    pool.approval.style.transform = `translateY(${(1 - k) * 40}px) scale(${(0.85 + 0.15 * k) * (1 - 0.2 * out)})`;
    pool.approval.style.opacity = String(clamp01(age / 0.2) * (1 - out));
    const amount = attn.metadata.amount ? `$${attn.metadata.amount}` : "";
    let stamp = "";
    if (approve && shown(approve)) {
      const s = backOut((t - at(approve)) / 0.4);
      stamp = `<div class="stamp" style="transform: rotate(-12deg) scale(${(2 - s).toFixed(3)}); opacity:${clamp01((t - at(approve)) / 0.15)}">APPROVED ✅</div>`;
    }
    set(
      pool.approval,
      `${stamp}<h3>✋ Mochi raised a paw</h3><p>Approve the pantry order?</p><div class="amount">${amount}</div><p>$${attn.metadata.over_budget_by} over this week's budget</p><div class="btns"><span class="btn yes">Approve</span><span class="btn">No</span></div>`
    );
  }

  renderConfetti(t, at) {
    const receipt = this.model.events.find((e) => e.kind === "receipt");
    const age = receipt ? t - at(receipt) : -1;
    if (age < 0 || age > 5.5) {
      set(this.confetti, "");
      return;
    }
    const r = rng(42);
    const bits = ["🍊", "🍃", "✨", "🍊", "🎉", "🍊"];
    let html = "";
    for (let i = 0; i < 70; i++) {
      const x = r() * 1920;
      const delay = r() * 1.2;
      const speed = 380 + r() * 260;
      const y = -60 + (age - delay) * speed;
      const rot = (age - delay) * (r() * 300 - 150);
      const sway = Math.sin((age - delay) * 3 + i) * 24;
      if (age < delay) continue;
      html += `<span style="left:${(x + sway).toFixed(0)}px;top:${y.toFixed(0)}px;transform:rotate(${rot.toFixed(0)}deg)">${bits[i % bits.length]}</span>`;
    }
    this.confetti.innerHTML = html;
  }
}

function fmtClock(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function fitStage(stage) {
  const fit = () => {
    const k = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    stage.style.transform = `translate(${(window.innerWidth - 1920 * k) / 2}px, ${(window.innerHeight - 1080 * k) / 2}px) scale(${k})`;
  };
  window.addEventListener("resize", fit);
  fit();
}
