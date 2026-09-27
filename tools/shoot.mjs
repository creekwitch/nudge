// Headless screenshot of a URL via raw CDP (no browser_exec dependency).
// usage: node shoot.mjs <url> <out.png> [width] [height]
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const [url, out, W = "1400", H = "1000"] = process.argv.slice(2);
const port = 9333 + Math.floor(Math.random() * 400);
const chrome = process.env.CHROME || "chromium";
const child = spawn(chrome, [
  "--headless=new", `--remote-debugging-port=${port}`,
  "--no-first-run", "--no-default-browser-check",
  "--disable-gpu", `--window-size=${W},${H}`,
  "--user-data-dir=/tmp/nudge-shoot-profile",
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdpTargets() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error("chromium never came up");
}

const ws = new WebSocket(await cdpTargets());
let id = 0;
const pending = new Map();
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
});
const send = (method, params = {}) => new Promise((res) => {
  const n = ++id; pending.set(n, res);
  ws.send(JSON.stringify({ id: n, method, params }));
});
await new Promise((r) => ws.addEventListener("open", r));

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride",
  { width: +W, height: +H, deviceScaleFactor: 2, mobile: false });
await send("Page.navigate", { url });
await sleep(2500); // let the app boot + fetch
const res = await send("Page.captureScreenshot", { format: "png" });
if (!res.result?.data) { console.error(JSON.stringify(res).slice(0, 500)); process.exit(1); }
writeFileSync(out, Buffer.from(res.result.data, "base64"));
console.log("saved", out);
child.kill();
process.exit(0);
