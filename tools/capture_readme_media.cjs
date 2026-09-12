// Capture real local UI and a document view of the actual Skill validation output.
const { chromium } = require("../web/node_modules/playwright");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const origin = new URL(process.argv[2] || "http://127.0.0.1:8772");
if (!["127.0.0.1", "localhost"].includes(origin.hostname)) throw Error("loopback_media_only");
const output = path.join(root, "docs/assets/readme");
const python = process.argv[3] || path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const escape = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const env = { ...process.env, COMMERCE_EVAL_DISABLE_CENTRAL_ENV: "1" };
for (const key of Object.keys(env)) if (/_API_KEY$|_TOKEN$|_SECRET$/.test(key)) delete env[key];
const report = JSON.parse(execFileSync(python, [
  "skills/ecommerce-eval-onboarding/scripts/validate_bundle.py",
  "skills/ecommerce-eval-onboarding/assets/bundle-example",
], { cwd: root, env, encoding: "utf8" }));
if (report.import_status !== "valid" || report.business_readiness.status !== "not_checked") throw Error("unexpected_skill_example");
fs.mkdirSync(output, { recursive: true });
const audit = { source: "actual_local_ui_and_skill_report", model_called: false, screenshots: [], browser_errors: [] };

function skillDocument(language) {
  const zh = language === "zh";
  const tr = (cn, en) => zh ? cn : en;
  const counts = report.coverage.counts;
  const statusRows = Object.entries(report.checks).map(([key, value]) =>
    "<tr><td>" + escape(key) + "</td><td class='ok'>" + escape(value.status) + "</td></tr>").join("");
  const resources = report.resources.map(item => "<tr><td><code>" + escape(item.path) + "</code></td><td class='ok'>" + escape(item.status) + "</td></tr>").join("");
  const conditions = report.coverage.conditions.map(item => "<tr><td><code>" + escape(item.condition_id) + "</code></td><td>" + escape(item.status) + "</td></tr>").join("");
  return `<!doctype html><html lang="${zh ? "zh-CN" : "en"}"><meta charset="utf-8"><title>Onboarding Skill / example handoff</title><style>
  *{box-sizing:border-box}body{margin:0;color:#17252c;background:#fff;font:18px/1.6 system-ui,"Microsoft YaHei",sans-serif;letter-spacing:0}
  main{max-width:1440px;margin:auto;padding:38px 50px}header{border-bottom:1px solid #d7e0e4;padding-bottom:22px}
  h1{font-size:30px;margin:6px 0}h2{font-size:20px;margin:24px 0 10px}p{margin:8px 0;color:#52606a}
  .label{color:#087e90;font-size:16px;font-weight:650}.columns{display:grid;grid-template-columns:1fr 1fr;gap:44px}
  table{width:100%;border-collapse:collapse;font-size:16px}td{padding:11px 8px;border-bottom:1px solid #e1e7e9;vertical-align:top;overflow-wrap:anywhere}
  code{font:15px/1.6 Consolas,monospace}.ok{color:#147a4c}.pending{color:#885d06;font-size:21px;font-weight:600}
  .note{border-left:3px solid #daac43;padding:10px 16px;background:#fffbef;font-size:16px}
  footer{margin-top:26px;border-top:1px solid #d7e0e4;padding-top:18px;font-size:15px;color:#52606a}
  </style><main><header><div class="label">E-commerce Eval / ecommerce-eval-onboarding 0.1.0</div>
  <h1>${tr("从产品调查到接入包", "From product investigation to an evaluation handoff")}</h1>
  <p>${tr("实际匿名示例与离线校验报告 · 文档预览，不是 Agent 成绩", "Actual anonymous example and offline report / document preview, not an Agent score")}</p></header>
  <div class="columns"><section><h2>${tr("可导入文件", "Importable resources")}</h2><table>${resources}</table>
  <h2>${tr("已完成的离线检查", "Completed offline checks")}</h2><table>${statusRows}</table>
  <p>${tr("通过真实导入服务在临时数据库校验；环境已清理。", "Validated through the real import service in a temporary database; cleaned up.")}</p></section>
  <section><h2>${tr("业务验收就绪状态", "Business acceptance readiness")}</h2>
  <div class="pending">${escape(report.business_readiness.status)}</div>
  <p><code>${escape(report.business_readiness.reason_codes.join(", "))}</code></p>
  <table>${conditions}</table>
  <h2>${tr("仍然缺少什么", "What is still missing")}</h2>
  <div class="note">${tr("实际产物与完整副作用台账尚未接入；失败恢复规则待用户确认。不能根据可导入文件推断业务通过。",
    "Actual artifacts and a complete effect journal are not connected. Recovery rules await confirmation. Importable files do not prove business acceptance.")}</div>
  </section></div><footer>${tr(`示例范围：${counts.covered} 个已覆盖条件，${counts.pending_confirmation} 个待确认；${counts.evidence_required} 个条件仍缺证据。计数可重叠，不代表整个产品覆盖率。`,
    `Example scope: ${counts.covered} covered conditions, ${counts.pending_confirmation} pending confirmation; ${counts.evidence_required} still require evidence. Counts overlap and do not measure whole-product coverage.`)}<br>
  Source: skills/ecommerce-eval-onboarding/assets/bundle-example + validate_bundle.py
  </footer></main></html>`;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const language of ["zh", "en"]) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1 });
      await context.addInitScript(language => {
        localStorage.setItem("commerce-eval-project", "readme-synthetic");
        localStorage.setItem("commerce-eval-language", language);
        localStorage.setItem("commerce-eval-theme", "light");
      }, language);
      const page = await context.newPage();
      page.on("pageerror", error => audit.browser_errors.push(error.message));
      page.on("request", request => {
        const url = new URL(request.url());
        if (url.protocol.startsWith("http") && url.origin !== origin.origin) audit.browser_errors.push("unexpected_external_request");
      });
      await page.goto(new URL("/traces/readme-a04-violation", origin).href);
      await page.getByRole("tab", { name: language === "zh" ? "指标" : "Metrics", exact: true }).click();
      const result = page.locator(".business-acceptance .requirement-result").first();
      await result.locator("summary").click();
      const effect = page.locator(".event-tree button").filter({ hasText: "side_effect.receipt" });
      if (await effect.count() !== 1) throw Error("receipt_event_missing");
      await effect.first().click();
      await page.locator(".event-inspector pre").evaluate(element => { element.scrollTop = element.scrollHeight; });
      const runBox = await page.locator(".run-page").boundingBox();
      await page.screenshot({ path: path.join(output, "acceptance-" + language + ".png"),
        clip: { x: runBox.x, y: runBox.y, width: runBox.width, height: Math.min(runBox.height, 990) } });
      audit.screenshots.push("acceptance-" + language + ".png");
      await page.goto(new URL("/datasets", origin).href);
      await page.getByRole("button", { name: /Commerce Business Acceptance/ }).click();
      await page.getByRole("textbox", { name: language === "zh" ? "搜索考题" : "Search cases" }).fill("A04");
      await page.locator(".case-disclosure > summary").click();
      const bankBox = await page.locator(".panel.detail-panel").boundingBox();
      await page.screenshot({ path: path.join(output, "bank-" + language + ".png"),
        clip: { x: bankBox.x, y: bankBox.y, width: bankBox.width, height: Math.min(bankBox.height, 880) } });
      audit.screenshots.push("bank-" + language + ".png");
      await page.setViewportSize({ width: 1440, height: 960 });
      const html = skillDocument(language);
      await page.setContent(html);
      await page.screenshot({ path: path.join(output, "skill-" + language + ".png") });
      audit.screenshots.push("skill-" + language + ".png");
      await context.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(audit, null, 2));
  if (audit.browser_errors.length) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
