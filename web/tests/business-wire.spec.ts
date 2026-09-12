import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

test("onboarding retains original banks and selects corrected grading without model calls", async ({ page, request }, testInfo) => {
  await installBank(request, page);
  const requested = page.waitForResponse(response => response.url().includes("scenario-templates?template_version=0.3.1"));
  await page.goto("/onboarding");
  const current = await (await requested).json();
  expect(current.items).toHaveLength(32);
  expect(current.items[0].business_requirements.every((row: { verifier_version: string }) => row.verifier_version === "1.1")).toBe(true);
  const picker = page.getByLabel("Bank version", { exact: true });
  await expect(picker).toHaveValue("0.3.1");
  expect(await picker.locator("option").evaluateAll(options => options.map(option => (option as HTMLOptionElement).value))).toEqual(["0.3.1", "0.3.0", "0.2.0"]);
  const original = page.waitForResponse(response => response.url().includes("scenario-templates?template_version=0.3.0"));
  await picker.selectOption("0.3.0");
  const previous = await (await original).json();
  expect(previous.items).toHaveLength(32);
  expect(previous.items[0].business_requirements.every((row: { verifier_version: string }) => row.verifier_version === "1.0")).toBe(true);
  await picker.selectOption("0.3.1");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("corrected-bank-selector.png"), fullPage: true });
});

async function installBank(request: APIRequestContext, page: Page) {
  const projectId = `business-wire-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  expect((await request.post("/api/v1/projects", { data: { project_id: projectId, name: "Business wire verification" } })).ok()).toBeTruthy();
  const installed = await request.post("/api/v1/onboarding/demo", { data: { project_id: projectId, template_ids: ["I01", "C03"], bank_version: "0.3.1" } });
  expect(installed.ok()).toBeTruthy();
  const bank = await installed.json();
  expect(bank.requires_explicit_model_configuration).toBe(true);
  expect(bank.executed).toBe(false);
  await page.addInitScript(id => {
    localStorage.setItem("commerce-eval-project", id);
    localStorage.setItem("commerce-eval-language", "en");
  }, projectId);
  return { projectId, bank };
}

test("browser experiment pin reaches real schema validation without any model execution", async ({ page, request, baseURL }) => {
  const { projectId } = await installBank(request, page);
  const absentProvider = `unregistered-${projectId}`;
  // Only the safe list is stubbed. The submitted experiment reaches the real API,
  // where an unregistered pin must be rejected before a job or model call exists.
  await page.route("**/api/v1/providers", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ items: [{ provider_id: absentProvider, kind: "custom", name: "Offline schema probe", version: 3, model: "fixture-model", enabled: true, configured: true }], presets: [], central_env: {} }),
  }));
  await page.goto("/experiments");
  await page.getByRole("button", { name: "Create experiment", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Provider version", { exact: true }).selectOption(`${absentProvider}:3`);
  await dialog.getByLabel("I authorize paid model requests for this experiment. Business effects remain simulated.").check();
  const posted = page.waitForResponse(response => response.url().endsWith("/api/v1/experiments") && response.request().method() === "POST");
  await dialog.getByRole("button", { name: "Run", exact: true }).click();
  const response = await posted;
  expect(response.status()).toBe(404);
  expect(await response.json()).toEqual({ detail: "provider_version_not_found" });
  const payload = response.request().postDataJSON();
  expect(payload.provider_version).toBe("3");
  expect(payload.allow_paid).toBe(true);
  expect(response.request().headers().origin).toBe(baseURL);
  const invalidType = await request.post("/api/v1/experiments", {
    headers: { Origin: baseURL! },
    data: { ...payload, provider_version: 3 },
  });
  expect(invalidType.status()).toBe(422);
  expect(await invalidType.json()).toEqual({ detail: "request_schema_invalid" });
  expect((await (await request.get(`/api/v1/experiments?project_id=${projectId}`)).json()).items).toHaveLength(0);
  await expect(dialog).toBeVisible();
});

test("real template readiness works before commit and changes invalidate the check", async ({ page, request }) => {
  const { projectId } = await installBank(request, page);
  const initial = (await (await request.get(`/api/v1/datasets?project_id=${projectId}`)).json()).items.length;
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Registered target", exact: true }).click();
  await page.getByLabel("Target", { exact: true }).selectOption("0");
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("All 32 scenarios", { exact: true }).uncheck();
  await page.locator(".wizard-case label").filter({ hasText: /^I01\s/ }).locator("input").check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const pending = page.waitForResponse(response => response.url().endsWith("/onboarding/check"));
  await page.getByRole("button", { name: "Check connection", exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON()).toMatchObject({ template_ids: ["I01"], template_version: "0.3.1" });
  expect(await response.json()).toMatchObject({ connection_ready: true, executed: false, business_readiness: { ready: true, tool_name_matching_required: false, collector: "builtin-business-environment-v1" } });
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  expect((await (await request.get(`/api/v1/datasets?project_id=${projectId}`)).json()).items).toHaveLength(initial);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.locator(".wizard-case label").filter({ hasText: /^C03\s/ }).locator("input").check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  await expect(page.locator(".evidence-readiness")).toContainText("Not yet collected / verified");
  await page.getByRole("button", { name: "Check connection", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByLabel("Bank version", { exact: true }).selectOption("0.2.0");
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  expect((await (await request.get(`/api/v1/experiments?project_id=${projectId}`)).json()).items).toHaveLength(0);
});
