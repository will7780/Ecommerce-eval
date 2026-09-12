import { expect, test, type Page, type Route } from "@playwright/test";

const project = { project_id: "ui-business", name: "Commerce UI checks", description: "", created_at: "2026-01-01T00:00:00Z" };
const preset = { provider_id: "deepseek", kind: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat", credential_env: "DEEPSEEK_API_KEY" };
const provider = { ...preset, version: 3, enabled: true, allow_localhost: false, endpoint_confirmed: true, endpoint_fingerprint: "endpoint-fixture", configured: true, credential_source: "central_env", configuration_status: "configured", error_type: null, last_check: null };
const central = { version: "env-revision-1", available: true, writable: true, source: "pointer", error_type: null };
const requirement = { requirement_id: "I01.preview_only", verifier_id: "no_effects", verifier_version: "1.0", subject: "Requested products", turn: null, expected: { forbidden_actions: ["publish"] }, required_evidence: ["effects", "artifacts"], applicable: true };
const caseRow = { contract_version: "1.2", case_id: "I01", scenario_id: "I01", name: "Prepare a preview without publishing", input: { message: "Prepare these products for preview only." }, business_requirements: [requirement], tags: ["commerce"], gates: [{ metric_id: "business_acceptance_pass", operator: "equals", expected: true, allow_na: false }] };
const dataset = { project_id: project.project_id, dataset_id: "business-bank", version: "0.3.0", name: "Business conditions", description: "", case_count: 1, created_at: project.created_at, cases: [caseRow] };
const targets = [
  { project_id: project.project_id, target_id: "business-agent", version: "0.3.0", name: "Business interface candidate", adapter_type: "business_interface", safe_for_eval: true, config: { tool_contract_set_id: "target-tools", tool_contract_version: "1" }, tags: {} },
  { project_id: project.project_id, target_id: "files-agent", version: "0.3.0", name: "File editor candidate", adapter_type: "file_editor", safe_for_eval: true, config: { tool_contract_set_id: "file-tools", tool_contract_version: "1" }, tags: {} },
  { project_id: project.project_id, target_id: "external", version: "1", name: "External HTTP target", adapter_type: "http", safe_for_eval: true, config: {}, tags: {} },
];

async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) }); }

async function fakePlatform(page: Page, override?: (route: Route, path: string) => Promise<boolean>) {
  await page.addInitScript(id => { localStorage.setItem("commerce-eval-project", id); localStorage.setItem("commerce-eval-language", "en"); localStorage.setItem("commerce-eval-theme", "dark"); }, project.project_id);
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (await override?.(route, path)) return;
    if (path === "/projects") return json(route, { items: [project] });
    if (path === "/providers") return json(route, { items: [provider], presets: [preset, { ...preset, provider_id: "laozhang", kind: "laozhang", name: "LaoZhang API", credential_env: "LAOZHANG_API_KEY", base_url: "https://api.laozhang.ai/v1", model: "" }], central_env: central });
    if (path === "/providers/csrf") return json(route, { csrf_token: "csrf-fixture" });
    if (path === "/datasets") return json(route, { items: [dataset] });
    if (path.startsWith("/datasets/")) return json(route, dataset);
    if (path === "/targets") return json(route, { items: targets });
    if (path === "/tool-contracts") return json(route, { items: [{ project_id: project.project_id, set_id: "target-tools", version: "1", tools: [], tool_count: 0 }, { project_id: project.project_id, set_id: "file-tools", version: "1", tools: [], tool_count: 0 }] });
    if (path === "/evaluators") return json(route, { sets: [{ project_id: project.project_id, set_id: "business", version: "1", metric_ids: ["business_acceptance_pass"] }], items: [] });
    if (path === "/experiments") return json(route, { items: [] });
    if (path === "/scenario-templates") return json(route, { items: [caseRow] });
    if (path === "/onboarding/check") return json(route, { status: "ready", connection: "connected", executed: false, checks: [{ code: "target_connected", status: "pass" }] });
    return json(route, { detail: "unexpected_test_request" }, 404);
  });
}

test("provider saves are separate from explicit paid checks; key is write-only", async ({ page }) => {
  let credentialPosts = 0, checks = 0, configurations = 0;
  const fixtureSecret = "fixture-only-credential-3842";
  await fakePlatform(page, async (route, path) => {
    if (route.request().method() !== "POST" || !path.startsWith("/providers")) return false;
    expect(route.request().headers()["x-csrf-token"]).toBe("csrf-fixture");
    expect(route.request().url()).not.toContain(fixtureSecret);
    if (path === "/providers") { configurations++; const body = route.request().postDataJSON(); expect(body.expected_version).toBe(3); expect(body).not.toHaveProperty("secret"); await json(route, provider); return true; }
    if (path.endsWith("/credential")) { credentialPosts++; expect(route.request().postDataJSON()).toEqual({ version: 3, secret: fixtureSecret, expected_env_version: central.version, acknowledge_shared: true }); await json(route, { provider_id: "deepseek", version: 3, configured: true, credential_source: "central_env", central_env: central }); return true; }
    if (path.endsWith("/check")) { checks++; expect(route.request().postDataJSON()).toEqual({ version: 3, allow_paid: true, model: "deepseek-chat" }); await json(route, { status: "failed", error_type: "provider_timeout", latency_ms: 20, checked_at: project.created_at, model: "deepseek-chat" }); return true; }
    return false;
  });
  await page.goto("/settings/providers");
  await expect(page.getByRole("heading", { name: "AI Providers" })).toBeVisible();
  await expect(page.locator(".sidebar nav a")).toHaveCount(6);
  await expect(page.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
  await page.getByTitle("Edit DeepSeek", { exact: true }).click();
  await page.getByLabel("Default model", { exact: true }).fill("deepseek-chat");
  await expect(page.getByRole("button", { name: "Save configuration", exact: true })).toBeDisabled();
  await page.getByLabel("I trust this endpoint to receive the referenced credential when a model request is explicitly started.").check();
  await page.getByRole("button", { name: "Save configuration", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(configurations).toBe(1); expect(checks).toBe(0);
  await page.getByTitle("Set API key DeepSeek", { exact: true }).click();
  await expect(page.getByLabel("API Key", { exact: true })).toHaveAttribute("type", "password");
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await page.getByLabel("API Key", { exact: true }).fill(fixtureSecret);
  await expect(page.getByRole("button", { name: "Save API key", exact: true })).toBeDisabled();
  await page.getByLabel("I understand this updates a shared central credential.").check();
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(credentialPosts).toBe(1); expect(checks).toBe(0);
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(fixtureSecret);
  await expect(page.locator("body")).not.toContainText(fixtureSecret);
  await page.getByTitle("Set API key DeepSeek", { exact: true }).click();
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByTitle("Test connection DeepSeek", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Run connection test", exact: true })).toBeDisabled();
  await page.getByLabel("I authorize one connection test. It sends a model request and may incur charges.").check();
  await page.getByRole("button", { name: "Run connection test", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("status")).toContainText("Connection failed");
  await expect(page.getByRole("button", { name: "Run connection test", exact: true })).toBeDisabled();
  expect(checks).toBe(1);
});

test("provider failed key write clears input and never echoes transport payload", async ({ page }) => {
  const marker = "fixture-echo-must-not-render";
  await fakePlatform(page, async (route, path) => {
    if (!path.endsWith("/credential")) return false;
    await json(route, { detail: `upstream rejected ${marker}` }, 409); return true;
  });
  await page.goto("/settings/providers");
  await page.getByTitle("Set API key DeepSeek", { exact: true }).click();
  await page.getByLabel("API Key", { exact: true }).fill(marker);
  await page.getByLabel("I understand this updates a shared central credential.").check();
  await page.getByRole("button", { name: "Save API key", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("provider_request_failed_409");
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  await expect(page.locator("body")).not.toContainText(marker);
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(marker);
});

test("real candidates require a pinned provider and renewed paid consent; external target is unchanged", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await fakePlatform(page, async (route, path) => {
    if (path !== "/experiments" || route.request().method() !== "POST") return false;
    requests.push(route.request().postDataJSON()); await json(route, { experiment_id: "created-fixture" }); return true;
  });
  await page.goto("/experiments");
  await page.getByRole("button", { name: "Create experiment", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  await dialog.getByLabel("Provider version", { exact: true }).selectOption("deepseek:3");
  await expect(dialog.getByLabel("Model", { exact: true })).toHaveValue("deepseek-chat");
  const consent = dialog.getByLabel("I authorize paid model requests for this experiment. Business effects remain simulated.");
  await consent.check();
  await dialog.getByLabel("Repetitions", { exact: true }).fill("2");
  await expect(consent).not.toBeChecked();
  await expect(dialog.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  await consent.check();
  await dialog.getByRole("button", { name: "Run", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(requests[0]).toMatchObject({ contract_version: "1.2", provider_id: "deepseek", provider_version: "3", model: "deepseek-chat", allow_paid: true, repetitions: 2 });
  expect(requests[0]).not.toHaveProperty("secret");
  await page.getByRole("button", { name: "Create experiment", exact: true }).click();
  await dialog.getByLabel("Target version", { exact: true }).selectOption("1");
  await expect(dialog.getByLabel("Provider version", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("Tool contract", { exact: true })).toHaveValue("1");
  await expect(dialog.getByLabel("Tool contract", { exact: true })).toBeDisabled();
  await dialog.getByLabel("Target version", { exact: true }).selectOption("2");
  await expect(dialog.getByLabel("Provider version", { exact: true })).not.toBeVisible();
  await expect(dialog).toContainText("keeps its own model and credentials");
  await dialog.getByRole("button", { name: "Run", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(requests[1]).not.toHaveProperty("provider_id"); expect(requests[1]).not.toHaveProperty("allow_paid");
});

test("business cases show requirements and missing evidence cannot be a false success", async ({ page }) => {
  const businessMetric = { metric_id: "business_acceptance_pass", metric_version: "1", group: "business", status: "error", value: false, reason_code: "evidence_missing", evidence_refs: [], na_reason: null, details: { requirement_results: [{ metric_id: "I01.preview_only", status: "error", reason_code: "evidence_missing", evidence_refs: [], details: { missing_reason: "effect_journal_incomplete" } }, { metric_id: "I01.rows", status: "pass", reason_code: "business_condition_satisfied", evidence_refs: ["artifact-1"], details: { actual_count: 20 } }] } };
  await fakePlatform(page, async (route, path) => {
    if (path !== "/traces/business-run") return false;
    await json(route, { trace: { trace_id: "business-run", project_id: project.project_id, target_id: "files-agent", target_version: "0.3.0", case_id: "I01", status: "completed", input: { message: "Preview these products" }, output: { summary: "Preview generated" }, started_at: project.created_at, events: [], resource_usage: {}, metadata: {} }, overall_pass: false, metrics: [businessMetric, { metric_id: "business_tool_attempt_count", metric_version: "1", group: "core", status: "pass", value: 8, reason_code: "recorded", evidence_refs: [], details: {} }], gates: [{ metric_id: "business_acceptance_pass", passed: false, operator: "equals", expected: true, actual: false, reason_code: "metric_error" }], annotations: [], business_evidence: { collector_id: "registered-file-collector", run_id: "business-run", project_id: project.project_id, company_id: "synthetic-company", started_at: project.created_at, ended_at: project.created_at, complete: false, omission_reasons: ["effect_journal_incomplete"] } }); return true;
  });
  await page.goto("/datasets");
  await page.getByRole("button", { name: /Business conditions/ }).click();
  await page.locator(".case-disclosure > summary").click();
  await expect(page.locator(".business-requirements > h3")).toHaveText("Business conditions");
  await expect(page.getByRole("heading", { name: "Capabilities / tools", exact: true })).not.toBeVisible();
  await page.locator(".business-requirements summary").click();
  await expect(page.locator(".evidence-tags")).toContainText("effects");
  await page.goto("/traces/business-run");
  await expect(page.locator(".run-statuses")).toContainText("Cannot verify");
  await expect(page.locator(".business-acceptance")).toContainText("effect_journal_incomplete");
  await expect(page.locator(".business-acceptance")).toContainText("registered-file-collector");
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(page.locator(".business-evidence-source")).toContainText("registered-file-collector");
  await expect(page.locator(".business-evidence-source")).toContainText("synthetic-company");
  await page.getByRole("tab", { name: "Metrics", exact: true }).click();
  await expect(page.locator("tr").filter({ hasText: "business_tool_attempt_count" })).toContainText("Diagnostic");
  await expect(page.locator(".metric-groups tr").filter({ hasText: "business_acceptance_pass" })).toContainText("Declared gate");
});

test("new onboarding asks for evidence, not a shared business tool name", async ({ page }) => {
  let templateVersion = "";
  await fakePlatform(page, async (route, path) => {
    if (path !== "/scenario-templates") return false;
    templateVersion = new URL(route.request().url()).searchParams.get("template_version") || "";
    await json(route, { items: [caseRow] }); return true;
  });
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Registered target", exact: true }).click();
  await page.getByLabel("Target", { exact: true }).selectOption("0");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Required business evidence", exact: true })).toBeVisible();
  await expect(page.locator(".capability-mappings")).not.toBeVisible();
  await expect(page.locator(".evidence-readiness")).toContainText("effects");
  await expect(page.locator(".evidence-readiness")).toContainText("Not yet collected / verified");
  expect(templateVersion).toBe("0.3.1");
});

test("settings are usable in both languages and themes without horizontal page overflow", async ({ page }, testInfo) => {
  await fakePlatform(page);
  await page.goto("/settings/providers");
  await expect(page.getByRole("heading", { name: "AI Providers" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("providers-dark.png"), fullPage: true });
  await page.getByTitle("Light theme", { exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByTitle("Switch to Chinese", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI 服务商" })).toBeVisible();
  await page.getByTitle("编辑 DeepSeek", { exact: true }).click();
  await expect(page.getByRole("button", { name: "保存配置", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("provider-editor-light-zh.png"), fullPage: true });
  await page.getByRole("dialog").getByRole("button", { name: "取消", exact: true }).click();
  await page.getByTitle("Dark theme", { exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("new bank installation opens model configuration without starting an experiment", async ({ page }) => {
  let starts = 0;
  await fakePlatform(page, async (route, path) => {
    if (path === "/experiments" && route.request().method() === "POST") { starts++; await json(route, { experiment_id: "must-not-start" }); return true; }
    if (path !== "/onboarding/demo") return false;
    expect(route.request().postDataJSON()).toMatchObject({ bank_version: "0.3.1", template_ids: ["I01"] });
    await json(route, { requires_explicit_model_configuration: true, executed: false, candidate_experiment_specs: [{ target_id: "files-agent", target_version: "0.3.0", dataset_id: dataset.dataset_id, dataset_version: dataset.version, evaluator_set_id: "business", evaluator_set_version: "1" }] }); return true;
  });
  await page.goto("/onboarding?mode=demo");
  for (let i = 0; i < 6; i++) await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("I confirm this configuration and sanitized data.").check();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page).toHaveURL(/experiments\?create=1/);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Target version", { exact: true })).toHaveValue("1");
  await expect(dialog.getByLabel("Tool contract", { exact: true })).toHaveValue("1");
  await expect(dialog.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  expect(starts).toBe(0);
});

test("paid experiment retry requires fresh consent and cancellation never executes", async ({ page }) => {
  let retries = 0;
  await fakePlatform(page, async (route, path) => {
    if (path === "/experiments") {
      await json(route, { items: [{ experiment_id: "paid-original", project_id: project.project_id, name: "Paid original", status: "failed", spec: { provider_id: "deepseek", provider_version: "3", model: "deepseek-chat", allow_paid: true }, total_runs: 1, completed_runs: 1, passed_runs: 0, failed_runs: 1, created_at: project.created_at }] });
      return true;
    }
    if (path !== "/experiments/paid-original/retry") return false;
    retries++;
    expect(route.request().postDataJSON()).toEqual({ allow_paid: true });
    await json(route, { experiment_id: "paid-retry" });
    return true;
  });
  await page.goto("/experiments");
  await page.getByTitle("Retry", { exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Retry paid experiment" });
  await expect(dialog).toContainText("deepseek / v3");
  await expect(dialog.getByRole("button", { name: "Retry", exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(retries).toBe(0);
  await page.getByTitle("Retry", { exact: true }).click();
  await dialog.getByLabel("I authorize a new paid run with the pinned configuration.").check();
  await dialog.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(retries).toBe(1);
  await page.getByTitle("Retry", { exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Retry", exact: true })).toBeDisabled();
});

test("connected external agents cannot bypass missing evidence collection", async ({ page }) => {
  await fakePlatform(page, async (route, path) => {
    if (path !== "/onboarding/check") return false;
    await json(route, { status: "evidence_required", connection_ready: true, executed: false, business_readiness: { ready: false, required_evidence: ["effects", "artifacts"], missing_evidence: ["effects"], collector: null, reason_code: "external_evidence_collector_required", tool_name_matching_required: false } }); return true;
  });
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Registered target", exact: true }).click();
  await page.getByLabel("Target", { exact: true }).selectOption("2");
  for (let i = 0; i < 4; i++) await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Check connection", exact: true }).click();
  await expect(page.locator(".evidence-readiness")).toContainText("Collection unavailable");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
});
