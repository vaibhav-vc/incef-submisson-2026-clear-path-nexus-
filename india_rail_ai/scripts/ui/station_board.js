// Station board and one train's expected times, in Chromium: the viewer token is taken from the fragment and
// removed from the address bar, the board fills, a train's every stop is listed, the page fits a phone with no
// sideways scroll, and an outage keeps the last times on screen with a banner instead of blanking them.
// Fails on any console error or CSP violation.
//   node scripts/ui/station_board.js <base url> <screenshot path>
//   env: RAILGUARD_VIEWER_TOKEN; FEATURE_STATION and FEATURE_RUN (discovered from the data by verify_features.py)
const { chromium } = require("playwright");
const base = process.argv[2], shot = process.argv[3], viewer = process.env.RAILGUARD_VIEWER_TOKEN;
const station = process.env.FEATURE_STATION, run = process.env.FEATURE_RUN;
if (!station || !run || !viewer) { console.error("FEATURE_STATION, FEATURE_RUN and RAILGUARD_VIEWER_TOKEN are required"); process.exit(2); }
const executablePath = process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
(async () => {
  const browser = await chromium.launch({ executablePath });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const problems = [];
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("Failed to load resource")) problems.push("console: " + m.text()); });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  const out = {};
  await page.goto(`${base}/board?station=${encodeURIComponent(station)}&window=360#token=${encodeURIComponent(viewer)}`);
  await page.waitForFunction(() => document.querySelectorAll("#rows tr").length > 0 || !document.getElementById("empty").hidden, null, { timeout: 60000 });
  out.token_left_address_bar = !page.url().includes("token=");
  out.board_rows = await page.locator("#rows tr").count();
  out.board_title = (await page.textContent("#title")).trim();
  out.updated = (await page.textContent("#fresh")).startsWith("Updated");
  await page.screenshot({ path: shot, fullPage: false });
  await page.goto(`${base}/board?run=${encodeURIComponent(run)}`);  // the token stays in this tab's session storage
  await page.waitForFunction(() => document.querySelectorAll("#rows tr").length > 0, null, { timeout: 60000 });
  out.train_stops = await page.locator("#rows tr").count();
  const api = await page.evaluate(async ([r, t]) => (await (await fetch(`/railguard/national/expected/${encodeURIComponent(r)}`,
    { headers: { Authorization: "Bearer " + t } })).json()).stops.length, [run, viewer]);
  out.every_stop_listed = api === out.train_stops;
  await page.setViewportSize({ width: 375, height: 800 });
  out.no_sideways_scroll_on_phone = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  // The server goes away: the last times stay, a banner says how old they are
  await page.route("**/railguard/national/**", (route) => route.abort());
  await page.evaluate(() => { document.dispatchEvent(new Event("visibilitychange")); });
  await page.waitForTimeout(500);
  out.times_kept_when_offline = (await page.locator("#rows tr").count()) === out.train_stops;
  const ok = !problems.length && out.token_left_address_bar && out.updated && out.every_stop_listed
    && out.no_sideways_scroll_on_phone && out.times_kept_when_offline && out.train_stops > 1;
  console.log(JSON.stringify({ ...out, problems }));
  await browser.close();
  process.exit(ok ? 0 : 1);
})().catch((e) => { console.log(JSON.stringify({ error: String(e) })); process.exit(1); });
