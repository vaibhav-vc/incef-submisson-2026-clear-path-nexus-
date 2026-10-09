// A cab whose link falls silent must stop showing guidance within the watchdog period.
// Run against scripts/ui/silent_server.py, which sends one advisory and then nothing.
const { chromium } = require("playwright");
const executablePath = process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
(async () => {
  const browser = await chromium.launch({ executablePath });
  const page = await browser.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(process.argv[2] + "/cab?run=TEST1@0#cab=abc.def");
  await page.waitForFunction(() => document.getElementById("statusText").textContent === "NORMAL", null, { timeout: 10000 });
  const shown = { status: await page.textContent("#statusText"), band: await page.textContent("#band"), hash: await page.evaluate(() => location.hash) };
  const t0 = Date.now();
  await page.waitForFunction(() => document.getElementById("statusText").textContent === "DATA UNAVAILABLE", null, { timeout: 40000 });
  const out = { shown, blanked_after_s: (Date.now() - t0) / 1000, band_after: await page.textContent("#band"), problems };
  console.log(JSON.stringify(out));
  await browser.close();
  process.exit(out.band_after === "--" && shown.hash === "" && !problems.length ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
