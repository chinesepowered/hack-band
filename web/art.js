// Original SVG cast for CapyBargain. Every character is a "soaking" bust in a
// 120x120 box: the bottom ~20 units sit under the hot-spring water.
//
// character(name, { eyes, t }) returns an SVG string. `eyes` is "open",
// "happy" (closed ^^) or "sleepy". `t` (seconds) drives tiny idle animations
// so frames are deterministic for video capture.

const CAPY = {
  head: "#C99063",
  body: "#B57D52",
  ear: "#A56C45",
  innerEar: "#E8B092",
  muzzle: "#B98154",
  line: "#6B4127",
};
const INK = "#2E1C12";
const BLUSH = "#F59C95";

const stroke = (c, w = 3) => `stroke="${c}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round"`;

function eyesFor(style, lx, rx, y, color = INK) {
  if (style === "happy") {
    return `<path d="M${lx - 5} ${y + 1} Q${lx} ${y - 5} ${lx + 5} ${y + 1}" fill="none" ${stroke(color, 3)}/>
            <path d="M${rx - 5} ${y + 1} Q${rx} ${y - 5} ${rx + 5} ${y + 1}" fill="none" ${stroke(color, 3)}/>`;
  }
  if (style === "sleepy") {
    return `<path d="M${lx - 5} ${y} Q${lx} ${y + 3.5} ${lx + 5} ${y}" fill="none" ${stroke(color, 3)}/>
            <path d="M${rx - 5} ${y} Q${rx} ${y + 3.5} ${rx + 5} ${y}" fill="none" ${stroke(color, 3)}/>`;
  }
  return `<ellipse cx="${lx}" cy="${y}" rx="4.2" ry="4.9" fill="${color}"/>
          <ellipse cx="${rx}" cy="${y}" rx="4.2" ry="4.9" fill="${color}"/>
          <circle cx="${lx + 1.5}" cy="${y - 1.9}" r="1.6" fill="#fff"/>
          <circle cx="${rx + 1.5}" cy="${y - 1.9}" r="1.6" fill="#fff"/>`;
}

const blush = (lx, rx, y, rxs = 7.5) =>
  `<ellipse cx="${lx}" cy="${y}" rx="${rxs}" ry="4.4" fill="${BLUSH}" opacity=".6"/>
   <ellipse cx="${rx}" cy="${y}" rx="${rxs}" ry="4.4" fill="${BLUSH}" opacity=".6"/>`;

function capybara(accessory, eyes) {
  const c = CAPY;
  return `
    <ellipse cx="60" cy="116" rx="52" ry="22" fill="${c.body}" ${stroke(c.line)}/>
    <ellipse cx="28" cy="30" rx="7.5" ry="7" fill="${c.ear}" ${stroke(c.line)}/>
    <ellipse cx="92" cy="30" rx="7.5" ry="7" fill="${c.ear}" ${stroke(c.line)}/>
    <ellipse cx="28" cy="28.5" rx="3.4" ry="3" fill="${c.innerEar}"/>
    <ellipse cx="92" cy="28.5" rx="3.4" ry="3" fill="${c.innerEar}"/>
    <rect x="11" y="29" width="98" height="74" rx="31" fill="${c.head}" ${stroke(c.line)}/>
    <rect x="33" y="55" width="54" height="40" rx="20" fill="${c.muzzle}"/>
    ${eyesFor(eyes, 34, 86, 51)}
    ${blush(23, 97, 69, 7)}
    <ellipse cx="51" cy="64" rx="3.6" ry="2.5" fill="#3B2316"/>
    <ellipse cx="69" cy="64" rx="3.6" ry="2.5" fill="#3B2316"/>
    <path d="M60 66 L60 75" ${stroke("#7C4E30", 2)}/>
    <path d="M52 77 Q56 82 60 77 Q64 82 68 77" fill="none" ${stroke("#4A2C1B", 2.6)}/>
    ${accessory}`;
}

const ACCESSORIES = {
  yuzu: `
    <path d="M60 6 L60 1" ${stroke("#3E7A3F", 2.5)}/>
    <circle cx="60" cy="18" r="12.5" fill="#FFB627" ${stroke("#C47A00")}/>
    <ellipse cx="55" cy="12.5" rx="3.6" ry="2.4" fill="#fff" opacity=".55"/>
    <circle cx="64" cy="20" r="1.1" fill="#E39400"/><circle cx="58" cy="22" r="1.1" fill="#E39400"/>
    <path d="M60 5 Q69 -3 77 3 Q69 10 60 5 Z" fill="#6CC070" ${stroke("#3E8A47", 2.2)}/>`,
  chefHat: `
    <circle cx="45" cy="13" r="10" fill="#fff" ${stroke("#C9BFB4")}/>
    <circle cx="60" cy="8" r="12" fill="#fff" ${stroke("#C9BFB4")}/>
    <circle cx="75" cy="13" r="10" fill="#fff" ${stroke("#C9BFB4")}/>
    <rect x="40" y="15" width="40" height="13" rx="5" fill="#fff" ${stroke("#C9BFB4")}/>
    <path d="M44 22 L76 22" ${stroke("#F2E6D9", 2)}/>`,
  glasses: `
    <circle cx="60" cy="16" r="11" fill="#FFD34D" ${stroke("#C29200")}/>
    <circle cx="60" cy="16" r="6.5" fill="none" ${stroke("#E3B51F", 2)}/>
    <ellipse cx="55.5" cy="12" rx="2.6" ry="1.8" fill="#fff" opacity=".6"/>
    <circle cx="34" cy="51" r="11" fill="rgba(255,255,255,.22)" ${stroke("#3B2A20", 3)}/>
    <circle cx="86" cy="51" r="11" fill="rgba(255,255,255,.22)" ${stroke("#3B2A20", 3)}/>
    <path d="M45 50 Q60 43 75 50" fill="none" ${stroke("#3B2A20", 3)}/>`,
};

function tortoise(eyes) {
  return `
    <ellipse cx="60" cy="96" rx="54" ry="34" fill="#6FA35A" ${stroke("#3F6E36")}/>
    <path d="M22 92 L38 76 L60 72 L82 76 L98 92" fill="none" ${stroke("#4E8241", 3)}/>
    <path d="M38 76 L36 100 M60 72 L60 102 M82 76 L84 100" fill="none" ${stroke("#4E8241", 3)}/>
    <circle cx="60" cy="60" r="30" fill="#B7DA8E" ${stroke("#557A3B")}/>
    ${eyesFor(eyes === "open" ? "sleepy" : eyes, 47, 73, 60, "#2D3A1E")}
    ${blush(42, 78, 70, 6.5)}
    <path d="M53 72 Q60 77.5 67 72" fill="none" ${stroke("#2D3A1E", 2.6)}/>
    <path d="M38 34 Q40 14 60 14 Q80 14 82 34 Z" fill="#F7DE8F" ${stroke("#B8913B")}/>
    <path d="M39 30 Q60 24 81 30 L81.5 34 Q60 29 38.5 34 Z" fill="#E8665B"/>
    <ellipse cx="60" cy="35" rx="40" ry="8.5" fill="#F2D27A" ${stroke("#B8913B")}/>
    <path d="M75 20 Q86 12 84 26" fill="none" ${stroke("#6CC070", 2.6)}/>`;
}

function hummingbird(eyes, t) {
  const flap = Math.sin(t * 38) * 22;
  const wing = (side) => {
    const x = side < 0 ? 30 : 90;
    const a = side * (28 + flap);
    return [0, 1].map(
      (ghost) => `<ellipse cx="${x}" cy="62" rx="27" ry="10" transform="rotate(${a - side * ghost * 14} ${x} 66)"
        fill="#A8EBE1" opacity="${ghost ? 0.28 : 0.72}" ${stroke("#2E8F84", ghost ? 0 : 2.4)}/>`
    ).join("");
  };
  return `
    ${wing(-1)}${wing(1)}
    <ellipse cx="60" cy="76" rx="31" ry="35" fill="#33BBA8" ${stroke("#1F7F72")}/>
    <ellipse cx="60" cy="90" rx="19" ry="19" fill="#DDF7EF"/>
    <path d="M47 70 Q60 80 73 70 Q68 82 60 83 Q52 82 47 70 Z" fill="#E2557A"/>
    <path d="M86 60 L118 65 L86 67 Z" fill="#3B3B3B" ${stroke("#2A2A2A", 1.5)}/>
    ${eyesFor(eyes, 49, 71, 57)}
    <ellipse cx="41" cy="66" rx="5.5" ry="3.6" fill="#FF8FB1" opacity=".9"/>
    <ellipse cx="79" cy="66" rx="5.5" ry="3.6" fill="#FF8FB1" opacity=".9"/>
    <path d="M40 46 Q60 26 80 46 Z" fill="#E8584F" ${stroke("#A3342E")}/>
    <path d="M76 45 Q92 44 94 49 Q82 51 73 48 Z" fill="#C9443C" ${stroke("#A3342E", 2)}/>
    <circle cx="60" cy="33" r="3.2" fill="#FFD34D"/>`;
}

function fox(eyes) {
  const sly =
    eyes === "open"
      ? `<path d="M34 56 Q41 50 48 56" fill="none" ${stroke(INK, 3.2)}/>
         <path d="M33 53.5 L30 51" ${stroke(INK, 2)}/>
         <ellipse cx="80" cy="55" rx="4.2" ry="4.9" fill="${INK}"/><circle cx="81.5" cy="53" r="1.6" fill="#fff"/>
         <path d="M84 50 L87 47.5" ${stroke(INK, 2)}/>`
      : eyesFor(eyes, 41, 79, 55);
  return `
    <ellipse cx="60" cy="116" rx="44" ry="18" fill="#F28A3A" ${stroke("#A3501A")}/>
    <path d="M20 44 L30 6 L52 30 Z" fill="#F28A3A" ${stroke("#A3501A")}/>
    <path d="M100 44 L90 6 L68 30 Z" fill="#F28A3A" ${stroke("#A3501A")}/>
    <path d="M28 34 L31 16 L43 30 Z" fill="#FFD9B8"/><path d="M92 34 L89 16 L77 30 Z" fill="#FFD9B8"/>
    <path d="M27.5 17 L30 6 L34 15 Z" fill="#5A3A2A"/><path d="M92.5 17 L90 6 L86 15 Z" fill="#5A3A2A"/>
    <path d="M14 56 Q16 28 60 26 Q104 28 106 56 Q102 84 60 100 Q18 84 14 56 Z" fill="#F28A3A" ${stroke("#A3501A")}/>
    <path d="M30 66 Q60 54 90 66 Q82 92 60 99 Q38 92 30 66 Z" fill="#FFF4E8"/>
    ${sly}
    ${blush(30, 90, 68, 6.5)}
    <ellipse cx="60" cy="70" rx="5.6" ry="4" fill="#3A2418"/>
    <path d="M53 79 Q60 83.5 68 77" fill="none" ${stroke("#3A2418", 2.6)}/>
    <path d="M42 102 L58 108 L42 115 Z" fill="#8E6AD8" ${stroke("#5E3FA8", 2.4)}/>
    <path d="M78 102 L62 108 L78 115 Z" fill="#8E6AD8" ${stroke("#5E3FA8", 2.4)}/>
    <circle cx="60" cy="108" r="4.4" fill="#A98BEA" ${stroke("#5E3FA8", 2.4)}/>`;
}

function mug(eyes, t) {
  const wisp = (x, phase) => {
    const y = 4 - ((t * 9 + phase) % 14);
    return `<path d="M${x} ${26 + y} q-5 -6 0 -12 q5 -6 0 -12" fill="none" ${stroke("#fff", 3.5)} opacity="${0.75 - ((t * 0.6 + phase / 14) % 1) * 0.5}"/>`;
  };
  return `
    ${wisp(48, 0)}${wisp(66, 7)}
    <path d="M92 52 Q110 52 110 68 Q110 86 92 86" fill="none" ${stroke("#6B4127", 9)}/>
    <path d="M92 52 Q110 52 110 68 Q110 86 92 86" fill="none" ${stroke("#FFFDF8", 4)}/>
    <rect x="22" y="34" width="72" height="80" rx="16" fill="#FFFDF8" ${stroke("#6B4127")}/>
    <ellipse cx="58" cy="37" rx="33" ry="7" fill="#8B5A36" ${stroke("#6B4127")}/>
    <ellipse cx="50" cy="35.5" rx="8" ry="2" fill="#B07A4F"/>
    ${eyesFor(eyes, 46, 70, 66)}
    ${blush(38, 78, 77, 6)}
    <path d="M52 78 Q58 84 64 78" fill="none" ${stroke(INK, 2.8)}/>
    <path d="M58 98 C54 93 47 96 50 101 L58 108 L66 101 C69 96 62 93 58 98 Z" fill="#F59C95"/>`;
}

export const CAST = {
  Mochi: { kind: "capy", role: "Head Buyer", emoji: "🍊", color: "#F0A020" },
  Tofu: { kind: "capy", role: "Pantry Keeper", emoji: "🥕", color: "#E07A5F" },
  Yuzu: { kind: "capy", role: "Treasurer", emoji: "🪙", color: "#C29200" },
  Shelly: { kind: "supplier", role: "Slow & Steady Farm", emoji: "🐢", color: "#4E8241" },
  Zippy: { kind: "supplier", role: "Zippy Express Pantry", emoji: "🐦", color: "#1F8F80" },
  Foxy: { kind: "supplier", role: "Foxy Wholesale", emoji: "🦊", color: "#D2691E" },
  Owner: { kind: "human", role: "Café owner (human)", emoji: "☕", color: "#8B5A36" },
};

export function character(name, { eyes = "open", t = 0 } = {}) {
  let body;
  switch (name) {
    case "Mochi": body = capybara(ACCESSORIES.yuzu, eyes); break;
    case "Tofu": body = capybara(ACCESSORIES.chefHat, eyes); break;
    case "Yuzu": body = capybara(ACCESSORIES.glasses, eyes); break;
    case "Shelly": body = tortoise(eyes); break;
    case "Zippy": body = hummingbird(eyes, t); break;
    case "Foxy": body = fox(eyes); break;
    default: body = mug(eyes, t);
  }
  return `<svg viewBox="-4 -6 128 130" xmlns="http://www.w3.org/2000/svg" aria-label="${name}" role="img">${body}</svg>`;
}

// A blinking schedule that looks natural but is a pure function of time.
export function blinkEyes(name, t, base = "open") {
  if (base !== "open") return base;
  const seed = [...name].reduce((a, ch) => a + ch.charCodeAt(0), 0);
  const period = 3.1 + (seed % 7) * 0.37;
  const phase = (t + seed * 0.13) % period;
  return phase < 0.14 ? "happy" : "open";
}
