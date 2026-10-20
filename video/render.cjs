// Render web/video.html frame by frame into video/capybargain-demo.mp4.
//
//   python3 -m http.server 8765 --bind 127.0.0.1      (from the repo root)
//   NODE_PATH=$(npm root -g) node video/render.cjs [--workers 4] [--from 0 --to 121] [--cut v2]
//
// Each worker steps its own Chromium page through a slice of the timeline
// (window.renderAt(t) is deterministic), pipes JPEG frames into ffmpeg, and
// the slices are joined and muxed with video/build/soundtrack.wav. --cut v2 renders
// web/video.html?cut=v2 from video/timeline-v2.json and video/build/v2/ instead.

const { chromium } = require("playwright");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), [])
);
const CUT = args.cut || "";
const URL = args.url || `http://127.0.0.1:8765/web/video.html${CUT ? `?cut=${CUT}` : ""}`;
const WORKERS = parseInt(args.workers || "4", 10);
const BUILD = path.join(__dirname, "build", CUT);
const OUT = path.join(__dirname, args.out || (CUT ? `capybargain-demo-${CUT}.mp4` : "capybargain-demo.mp4"));

async function renderSlice(k, first, last, fps) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", (e) => console.error(`[worker ${k}] page error:`, e.message));
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.directorReady === true);
  const part = path.join(BUILD, `part_${k}.mp4`);
  const ff = spawn("ffmpeg", [
    "-v", "error", "-y",
    "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", String(fps),
    part,
  ], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((resolve, reject) => ff.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}`)))));
  const started = Date.now();
  for (let i = first; i < last; i++) {
    await page.evaluate((t) => window.renderAt(t), i / fps);
    const jpg = await page.screenshot({ type: "jpeg", quality: 92 });
    if (!ff.stdin.write(jpg)) await new Promise((r) => ff.stdin.once("drain", r));
    if ((i - first) % 300 === 0) {
      const rate = (i - first) / ((Date.now() - started) / 1000 || 1);
      console.log(`[worker ${k}] frame ${i - first}/${last - first} (${rate.toFixed(1)} fps)`);
    }
  }
  ff.stdin.end();
  await done;
  await browser.close();
  return part;
}

(async () => {
  fs.mkdirSync(BUILD, { recursive: true });
  const timeline = JSON.parse(fs.readFileSync(path.join(__dirname, CUT ? `timeline-${CUT}.json` : "timeline.json"), "utf8"));
  const fps = timeline.fps;
  const from = Math.round(parseFloat(args.from || "0") * fps);
  const to = Math.round(parseFloat(args.to || String(timeline.duration)) * fps);
  const per = Math.ceil((to - from) / WORKERS);
  console.log(`rendering ${to - from} frames at ${fps} fps with ${WORKERS} workers`);
  const parts = await Promise.all(
    Array.from({ length: WORKERS }, (_, k) => renderSlice(k, from + k * per, Math.min(to, from + (k + 1) * per), fps))
  );
  const list = path.join(BUILD, "parts.txt");
  fs.writeFileSync(list, parts.map((p) => `file '${p}'`).join("\n"));
  const silent = path.join(BUILD, "video_only.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", silent]);
  execFileSync("ffmpeg", [
    "-v", "error", "-y",
    "-i", silent,
    "-ss", String(from / fps), "-i", path.join(BUILD, "soundtrack.wav"),
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
    "-shortest", "-movflags", "+faststart",
    OUT,
  ]);
  console.log("wrote", OUT);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
