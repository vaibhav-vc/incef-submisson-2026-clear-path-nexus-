// The tabletop console (demonstration network) in Chromium: load a scenario, run it, rank alternatives.
//   node scripts/ui/tabletop_console.js <base url> <screenshot path>   (env RAILGUARD_CONTROLLER_TOKEN)
const { chromium } = require("playwright");
const base = process.argv[2], shot = process.argv[3], controller = process.env.RAILGUARD_CONTROLLER_TOKEN;
const executablePath = process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
let out0;
(async () => {
  const browser = await chromium.launch({ executablePath });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const problems = [];
  let signedIn = false;  // before a token is entered the server rightly refuses (401/403): not a fault of the page
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (!signedIn && /status of 40[13]/.test(m.text())) return;
    problems.push("console: " + m.text());
  });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));  // a script error is a fault at any time
  await page.goto(base + "/control");
  out0 = { refused_before_token_shown: false };
  await page.waitForFunction(() => document.getElementById("simError").textContent.includes("unavailable"), null,
    { timeout: 15000 }).then(() => { out0.refused_before_token_shown = true; }, () => {});
  signedIn = true;
  await page.fill("#token", controller);
  await page.dispatchEvent("#token", "change");
  await page.waitForFunction(() => document.querySelectorAll("#scenario option").length > 0, null, { timeout: 30000 });
  const out = { ...out0, scenarios: await page.locator("#scenario option").count() };
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
