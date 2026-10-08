// The tabletop console (demonstration network) in Chromium: load a scenario, run it, rank alternatives.
//   node scripts/ui/tabletop_console.js <base url> <screenshot path>   (env RAILGUARD_CONTROLLER_TOKEN)
const { chromium } = require("playwright");
const base = process.argv[2], shot = process.argv[3], controller = process.env.RAILGUARD_CONTROLLER_TOKEN;
const executablePath = process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
(async () => {
  const browser = await chromium.launch({ executablePath });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  await page.goto(base + "/control");
  await page.fill("#token", controller);
  await page.dispatchEvent("#token", "change");
  await page.waitForFunction(() => document.querySelectorAll("#scenario option").length > 0, null, { timeout: 30000 });
  const out = { scenarios: await page.locator("#scenario option").count() };
  await page.click("#loadScenario");
  await page.waitForFunction(() => document.getElementById("clock").textContent.trim() !== "", null, { timeout: 30000 });
  await page.click("#recommend");
  await page.waitForFunction(() => document.getElementById("recState").textContent.trim() !== "" &&
    !/no recommendation/i.test(document.getElementById("recState").textContent), null, { timeout: 60000 });
  out.recommendation_state = (await page.textContent("#recState")).trim();
  out.candidates_shown = await page.locator("#candidates > *").count();
  out.audit_entries = await page.locator("#audit > *").count();
  await page.screenshot({ path: shot });
  out.problems = problems;
  console.log(JSON.stringify(out));
  await browser.close();
  process.exit(!problems.length && out.scenarios > 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
