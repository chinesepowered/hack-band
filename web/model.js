// Turns a Band transcript (capybargain/transcript.py) into a timeline the
// onsen UI can render at any moment t.

const MENTION = /@\[\[([0-9a-f-]{36})\]\]/g;

export function buildModel(transcript) {
  const people = new Map();
  for (const room of transcript.rooms) {
    for (const p of room.participants) {
      people.set(p.id, { name: p.type === "User" ? "Owner" : p.name, type: p.type });
    }
  }
  const all = transcript.rooms.flatMap((r) => r.messages);
  const t0 = Math.min(...all.map((m) => Date.parse(m.inserted_at)));
  const secs = (iso) => (Date.parse(iso) - t0) / 1000;

  const rooms = transcript.rooms.map((r, i) => {
    const agents = r.participants.filter((p) => p.type === "Agent").map((p) => p.name);
    return {
      id: r.id,
      title: r.title,
      kind: i === 0 ? "hq" : "supplier",
      supplier: i === 0 ? null : agents.find((n) => n !== "Mochi"),
    };
  });
  const roomById = new Map(rooms.map((r) => [r.id, r]));

  const events = [];
  transcript.rooms.forEach((r) => {
    for (const m of r.messages) {
      const sender = m.sender_type === "User" ? "Owner" : m.sender_name;
      let who = sender;
      if (m.message_type === "participant") {
        const p = people.get(m.metadata?.participant_id);
        who = p ? p.name : sender;
      }
      const text = (m.content || "")
        .replace(MENTION, (_, id) => `@${people.get(id)?.name ?? "someone"}`)
        .replace(/(@\w+)( \1\b)+/g, "$1");
      const e = {
        id: m.id,
        room: roomById.get(r.id),
        type: m.message_type,
        sender: who,
        senderType: m.sender_type,
        ts: secs(m.inserted_at),
        text,
        metadata: m.metadata || {},
      };
      e.kind = classify(e);
      events.push(e);
    }
  });
  events.sort((a, b) => a.ts - b.ts);
  events.forEach((e, i) => (e.index = i));

  const tasks = (transcript.board?.tasks || []).map((task) => ({
    number: task.number,
    subject: task.subject,
    history: task.history.map((h) => ({
      ts: secs(h.at),
      event: h.event,
      status: h.payload?.status?.to,
      comment: h.payload?.text,
    })),
  }));

  return {
    rooms,
    events,
    tasks,
    goal: transcript.board?.goal_title || "",
    duration: Math.max(...events.map((e) => e.ts)),
  };
}

function classify(e) {
  if (e.type === "participant") return "join";
  if (e.type === "thought") return "thought";
  if (e.type === "task") return "link";
  if (e.type === "attention") return e.metadata.resolves ? "resolved" : "attention";
  if (e.type !== "text") return e.type;
  const t = e.text.toLowerCase();
  if (e.senderType === "User") return /approve/.test(t) ? "approve" : "owner";
  if (t.includes("| on shelf")) return "restock";
  if (t.includes("needed within")) return "rfq";
  if (t.includes("could you do")) return "counter";
  if (t.includes("purchase order")) return "po";
  if (t.includes("unit price") && /final offer|very best/.test(t)) return "final";
  if (t.includes("unit price")) return "quote";
  if (t.includes("weekly budget")) return "budget";
  if (t.includes("budget check please")) return "budget-ask";
  if (t.includes("found a deal")) return "approval-ask";
  if (t.includes("all done")) return "receipt";
  if (t.includes("logged")) return "logged";
  if (t.includes("confirmed")) return "confirm";
  if (t.includes("on it")) return "on-it";
  if (t.includes("yay")) return "yay";
  return "text";
}

// --- markdown ----------------------------------------------------------------------

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function inline(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*]+?)\*/g, "$1<i>$2</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/@(Owner|Mochi|Tofu|Yuzu|Shelly|Zippy|Foxy)\b/g, '<span class="mention">@$1</span>');
}

export function parseTable(text) {
  const lines = text.split("\n").filter((l) => l.trim().startsWith("|"));
  if (lines.length < 2) return null;
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim().replace(/^\*+|\*+$/g, ""));
  const headers = cells(lines[0]).map((h) => h.toLowerCase());
  const rows = lines.slice(2).map(cells).filter((r) => r.length === headers.length);
  return { headers, rows: rows.map((r) => Object.fromEntries(headers.map((h, i) => [h, r[i]]))) };
}

export function splitTable(text) {
  const lines = text.split("\n");
  const first = lines.findIndex((l) => l.trim().startsWith("|"));
  if (first < 0) return { before: text.trim(), after: "" };
  let last = first;
  while (last + 1 < lines.length && lines[last + 1].trim().startsWith("|")) last++;
  return {
    before: lines.slice(0, first).join("\n").trim(),
    after: lines.slice(last + 1).join("\n").trim(),
  };
}

export function markdown(text) {
  const out = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith("|")) {
      let j = i;
      while (j + 1 < lines.length && lines[j + 1].trim().startsWith("|")) j++;
      const table = parseTable(lines.slice(i, j + 1).join("\n"));
      if (table) {
        out.push(
          `<table class="md"><tr>${table.headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` +
            table.rows.map((r) => `<tr>${table.headers.map((h) => `<td>${inline(r[h])}</td>`).join("")}</tr>`).join("") +
            `</table>`
        );
      }
      i = j;
    } else if (lines[i].trim()) {
      out.push(`<p>${inline(lines[i])}</p>`);
    }
  }
  return out.join("");
}

// --- numbers ---------------------------------------------------------------------------

export const dollars = (s) => parseFloat(String(s).replace(/[^0-9.]/g, ""));
export const days = (s) => parseInt(String(s).match(/(\d+)/)?.[1] ?? "0", 10);
export const fmt = (n) => `$${n.toFixed(2)}`;

export function deliveryDays(text) {
  return days(text.match(/delivery in \**(\d+) days?/i)?.[1] ?? "0");
}

// --- derived state at time t -------------------------------------------------------------

// The quote board: items (rows) × suppliers (columns).
export function quoteBoard(model, shown) {
  const restock = model.events.find((e) => e.kind === "restock" && shown(e));
  const items = restock
    ? parseTable(restock.text).rows.map((r) => ({ item: r.item, order: r.order, deadline: days(r["runs out in"]) }))
    : [];
  const suppliers = model.rooms.filter((r) => r.kind === "supplier").map((r) => r.supplier);
  const order = ["Shelly", "Zippy", "Foxy"];
  suppliers.sort((a, b) => order.indexOf(a) - order.indexOf(b));

  const cols = suppliers.map((name) => {
    const quote = model.events.find((e) => e.kind === "quote" && e.sender === name && shown(e));
    const final = model.events.find((e) => e.kind === "final" && e.sender === name && shown(e));
    const confirmed = model.events.some((e) => e.kind === "confirm" && e.sender === name && shown(e));
    const prices = {};
    if (quote) for (const r of parseTable(quote.text).rows) prices[r.item] = dollars(r["unit price"]);
    const finals = {};
    if (final) for (const r of parseTable(final.text).rows) finals[r.item] = dollars(r["unit price"]);
    return {
      name,
      quoted: !!quote,
      days: quote ? deliveryDays(quote.text) : null,
      prices,
      finals,
      confirmed,
      upsell: quote && /psst/i.test(quote.text),
      total: quote ? dollars(quote.text.match(/Total: \$([0-9,.]+)/)?.[1] ?? "0") : null,
    };
  });

  const picked = model.events.some((e) => e.kind === "thought" && /picking winners/i.test(e.text) && shown(e));
  const winners = {};
  if (picked) {
    for (const it of items) {
      const onTime = cols.filter((c) => c.prices[it.item] != null && c.days <= it.deadline);
      const pool = onTime.length ? onTime : cols.filter((c) => c.prices[it.item] != null);
      pool.sort((a, b) => a.prices[it.item] - b.prices[it.item] || a.days - b.days);
      if (pool[0]) winners[it.item] = pool[0].name;
    }
  }
  return { items, cols, winners, picked };
}

export function taskStates(model, tNow) {
  return model.tasks.map((task) => {
    let status = null;
    let comment = "";
    let created = false;
    for (const h of task.history) {
      if (h.ts > tNow) break;
      if (h.event === "created") created = true;
      if (h.status) status = h.status;
      if (h.comment) comment = h.comment;
    }
    return { ...task, created, status: created ? status || "pending" : null, comment };
  });
}

export function budgetState(model, shown) {
  const budget = model.events.find((e) => e.kind === "budget" && shown(e));
  if (!budget) return null;
  const row = parseTable(budget.text).rows[0];
  const approved = model.events.some((e) => e.kind === "approve" && shown(e));
  const ask = model.events.find((e) => e.kind === "approval-ask" && shown(e));
  const saved = ask ? dollars(ask.text.match(/\*\*\$([0-9.,]+) less\*\*/)?.[1] ?? "0") : null;
  return {
    budget: dollars(row["weekly budget"]),
    spent: dollars(row["spent so far"]),
    left: dollars(row.left),
    order: dollars(row["this order"]),
    over: dollars(budget.text.match(/\*\*\$([0-9.,]+) over\*\*/)?.[1] ?? "0"),
    approved,
    saved,
  };
}
