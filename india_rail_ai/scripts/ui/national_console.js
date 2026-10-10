// National console and cab, end to end in Chromium: live push, every train with PIN codes and its route, the
// advisor, freight pathing, a delay recorded and ranked, a cab link issued and opened, a decision pushed to the
// cab, a forged link refused, the link revoked and the open cab cleared. Fails on any console error or CSP violation.
//   node scripts/ui/national_console.js <base url> <screenshot path>
//   env: RAILGUARD_CONTROLLER_TOKEN; FEATURE_TRAIN (a train in the twin) and FEATURE_QUERY (a word of a train name),
//   both discovered from the data by scripts/verify_features.py
const { chromium } = require("playwright");
const base = process.argv[2], shot = process.argv[3], controller = process.env.RAILGUARD_CONTROLLER_TOKEN;
const train = process.env.FEATURE_TRAIN, query = process.env.FEATURE_QUERY;
if (!train || !query) { console.error("FEATURE_TRAIN and FEATURE_QUERY are required"); process.exit(2); }
const executablePath = process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
(async () => {
  const browser = await chromium.launch({ executablePath });
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
  const problems = [];
  const watch = (p) => {
    p.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
    p.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  };
  const con = await ctx.newPage(); watch(con);
  await con.goto(base + "/control/national");
  await con.fill("#token", controller);
  await con.dispatchEvent("#token", "change");
  await con.waitForFunction(() => document.getElementById("liveBadge").textContent === "LIVE PUSH", null, { timeout: 60000 });
  const out = { live_push: true };
  await con.fill("#tq", query);
  await con.click("#tsearch");
  await con.waitForSelector("#tresults .runitem", { timeout: 30000 });
  out.trains_found = await con.locator("#tresults .runitem").count();
  await con.locator("#tresults .runitem").first().click();
  await con.waitForSelector("#tdetail table tbody tr", { timeout: 30000 });
  out.stops = await con.locator("#tdetail table tbody tr").count();
  out.pin_codes = await con.$$eval("#tdetail table tbody tr td:nth-child(3)", (tds) => tds.filter((t) => /^\d{6}$/.test(t.textContent)).length);
  await con.waitForFunction(() => document.querySelectorAll("#atable tbody tr").length > 0, null, { timeout: 30000 });
  out.advisor_rows = await con.locator("#atable tbody tr").count();
  await con.fill("#fn", "80");
  await con.click("#fplan");
  await con.waitForFunction(() => document.getElementById("fresult").textContent.includes("pathed"), null, { timeout: 90000 });
  out.freight = (await con.textContent("#fresult")).trim().slice(0, 120);
  await con.fill("#number", train);
  await con.click("#find");
  await con.waitForSelector("#runs .runitem", { timeout: 30000 });
  await con.locator("#runs .runitem").first().click();
  await con.waitForFunction(() => document.getElementById("selRun").textContent !== "—", null, { timeout: 30000 });
  const run = (await con.textContent("#selRun")).trim();
  await con.click("#issueCab");
  await con.waitForFunction(() => !document.getElementById("cabIssued").hidden, null, { timeout: 30000 });
  const link = await con.inputValue("#cabUrl");
  out.cab_link_carries_capability_in_fragment = /#cab=[^&]+\.[0-9a-f]{64}$/.test(link);
  const cab = await ctx.newPage(); watch(cab);
  const t0 = Date.now();
  await cab.goto(link);
  await cab.waitForFunction(() => !["Connecting…", "DATA UNAVAILABLE"].includes(document.getElementById("statusText").textContent), null, { timeout: 30000 });
  out.cab_first_advisory_s = (Date.now() - t0) / 1000;
  out.cab_address_bar_keeps_token = (await cab.evaluate(() => location.href)).includes("cab=");
  const before = (await cab.textContent("#schedule")).trim();
  await con.fill("#delay", "25");
  const t1 = Date.now();
  await con.click("#disrupt");
  await cab.waitForFunction((b) => document.getElementById("schedule").textContent.trim() !== b, before, { timeout: 20000 });
  out.cab_push_after_decision_s = (Date.now() - t1) / 1000;
  out.cab_status_after_delay = (await cab.textContent("#statusText")).trim();
  await con.click("#recommend");
  await con.waitForFunction(() => document.getElementById("recState").textContent !== "no recommendation", null, { timeout: 60000 });
  out.recommendation_state = (await con.textContent("#recState")).trim();
  out.candidates_shown = await con.locator("#candidates > *").count();
  const forged = await ctx.newPage(); watch(forged);
  await forged.goto(base + `/cab?run=${encodeURIComponent(run)}#cab=` + link.split("#cab=")[1].replace(/.$/, (c) => (c === "0" ? "1" : "0")));
  await forged.waitForFunction(() => document.getElementById("statusText").textContent === "DATA UNAVAILABLE", null, { timeout: 20000 });
  out.forged_link_refused = (await forged.textContent("#headline")).includes("not valid for this train");
  // Revoking the link ends the open cab stream: the cab clears its guidance and says the link is no longer valid.
  await con.click("#revokeCab");
  await cab.waitForFunction(() => document.getElementById("headline").textContent.includes("not valid for this train"),
    null, { timeout: 30000 });
  out.revoked_link_clears_cab = (await cab.textContent("#statusText")).trim() === "DATA UNAVAILABLE" &&
    (await cab.textContent("#threats")).includes("No current data");
  await con.screenshot({ path: shot, fullPage: false });
  out.problems = problems.filter((p) => !p.includes("403"));  // the forged link's refused stream is expected
  console.log(JSON.stringify(out));
  await browser.close();
  const ok = !out.problems.length && out.cab_link_carries_capability_in_fragment && !out.cab_address_bar_keeps_token &&
    out.forged_link_refused && out.revoked_link_clears_cab && out.trains_found > 0 && out.pin_codes > 0 &&
    out.advisor_rows > 0;
  process.exit(ok ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
