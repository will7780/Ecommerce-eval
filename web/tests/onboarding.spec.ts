import { expect, test } from "@playwright/test";

test("web upload validates, imports unscored, separates model inputs and preserves evaluations", async ({ page, request }, testInfo) => {
  const suffix = `${testInfo.project.name}-${Date.now()}`;
  const project = `upload-${suffix}`;
  const traceId = `input-${suffix}`;
  await request.post("/api/v1/projects", { data: { project_id: project, name: "Browser upload test" } });
  await page.addInitScript(p => { localStorage.setItem("commerce-eval-project", p); localStorage.setItem("commerce-eval-language", "en"); }, project);
  await page.goto("/onboarding?mode=import&kind=trace");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const trace = { contract_version: "1.1", trace_id: traceId, project_id: project, target_id: "offline", target_version: "1", input: { message: "Original request" }, output: { task_completed: true, summary: "Simulated only" }, events: [
    { event_id: "snapshot-a", sequence: 0, kind: "model.input", attributes: { snapshot_id: "s-a", model_call_id: "m-a", round: 0, captured: true, source: "test", messages: [{ role: "system", content: "System alpha" }, { role: "developer", content: "Developer boundary" }, { role: "user", content: "User alpha" }], tools: [] } },
    { event_id: "snapshot-b", sequence: 1, kind: "model.input", attributes: { snapshot_id: "s-b", model_call_id: "m-b", round: 1, captured: true, source: "test", messages: [{ role: "system", content: "System beta" }, { role: "user", content: "User beta token=example-sensitive" }], tools: [] } },
  ] };
  await page.getByLabel("Upload files").setInputFiles({ name: "trace.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(trace)) });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".preview-json")).toContainText("[REDACTED]");
  await expect(page.locator(".preview-json")).not.toContainText("example-sensitive");
  for (let i = 0; i < 4; i++) await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("I confirm this configuration and sanitized data.").check();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Saved", exact: true })).toBeVisible();
  let detail = await (await request.get(`/api/v1/traces/${traceId}`)).json();
  expect(detail.overall_pass).toBeNull();
  await page.goto(`/traces/${traceId}`);
  await expect(page.getByRole("heading", { name: "System Input", exact: true })).toBeVisible();
  await expect(page.locator(".input-columns")).toContainText("System alpha");
  await expect(page.locator(".input-columns")).not.toContainText("Developer boundary");
  await page.getByLabel("Model call", { exact: true }).selectOption("1");
  await expect(page.locator(".input-columns")).toContainText("System beta");
  await expect(page.locator(".input-columns")).not.toContainText("System alpha");
  await page.getByRole("tab", { name: "Context", exact: true }).click();
  await page.getByLabel("Model call", { exact: true }).selectOption("0");
  await expect(page.locator(".ordered-messages")).toContainText("Developer boundary");

  await request.post("/api/v1/datasets", { data: { project_id: project, dataset_id: "checks", version: "1", name: "Upload checks", cases: [{ case_id: "complete", name: "Completion check", outcome_assertions: { task_completed: true }, gates: [{ metric_id: "outcome_assertion_pass_rate", operator: "min", expected: 1 }] }] } });
  await request.post("/api/v1/tool-contracts", { data: { project_id: project, set_id: "checks", version: "1", tools: [] } });
  await request.post("/api/v1/evaluator-sets", { data: { project_id: project, set_id: "checks", version: "1", metric_ids: ["outcome_assertion_pass_rate"] } });
  for (let i = 0; i < 2; i++) {
    await page.getByRole("button", { name: "Evaluate / re-evaluate" }).click();
    await page.getByRole("dialog").getByRole("combobox", { name: "Case", exact: true }).selectOption("complete");
    await page.getByRole("button", { name: "Evaluate", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  }
  detail = await (await request.get(`/api/v1/traces/${traceId}`)).json();
  expect(detail.evaluation_history).toHaveLength(2);
  await page.getByRole("tab", { name: "Metrics", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Evaluation history" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("upload-evaluation.png"), fullPage: true });
});

test("invalid upload can be corrected; historical system is not invented", async ({ page, request }, testInfo) => {
  const project = `invalid-${testInfo.project.name}-${Date.now()}`;
  await request.post("/api/v1/projects", { data: { project_id: project, name: "Invalid upload test" } });
  await page.addInitScript(p => { localStorage.setItem("commerce-eval-project", p); }, project);
  await page.goto("/onboarding?mode=import");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Upload files").setInputFiles({ name: "bad.jsonl", mimeType: "text/plain", buffer: Buffer.from('{"trace_id":"incomplete"}\nnot-json') });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  await expect(page.getByRole("table")).toContainText("invalid");
  await page.getByRole("button", { name: "Back", exact: true }).click();
  const id = `legacy-${Date.now()}`;
  await request.post("/api/v1/traces", { data: { trace_id: id, project_id: project, target_id: "offline", target_version: "1", input: { message: "Only historical request" } } });
  await page.goto(`/traces/${id}`);
  await expect(page.locator(".capture-missing")).toHaveText("Not captured");
  await expect(page.locator(".input-columns")).toContainText("Only historical request");
});
