import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.clear());
});

test("dashboard, trace drill-down, theme and language work", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop workflow");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByLabel("Project")).toHaveValue("commerce-demo");
  await expect(page.locator(".stat-card").filter({ hasText: "Pass rate" })).toBeVisible();

  await page.getByTitle("Switch to Chinese").click();
  await expect(page.getByRole("heading", { name: "仪表盘" })).toBeVisible();
  await page.getByTitle("Light theme").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await page.getByRole("link", { name: "运行轨迹" }).click();
  await expect(page.getByRole("heading", { name: "运行轨迹" })).toBeVisible();
  await expect(page.getByText("listing-launch", { exact: true })).toBeVisible();
  const launchRow = page.getByRole("row").filter({ hasText: "listing-launch" });
  await launchRow.getByTitle("查看运行").click();
  await expect(page.getByRole("heading", { name: "trace-listing-launch" })).toBeVisible();
  await expect(page.getByText("Confirm publication", { exact: true }).first()).toBeVisible();

  await page.getByRole("tab", { name: "工具" }).click();
  await expect(page.getByRole("table").getByText("catalog.generate_listing", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByText("catalog.upload_listing", { exact: true })).toBeVisible();
  await expect(page.getByRole("table").getByText("pricing.audit_margin", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "参数" }).click();
  await expect(page.getByText("Intent score", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "指标" }).click();
  await expect(page.locator(".tab-content > .metric-groups").getByText("task_completion", { exact: true })).toBeVisible();

  const screenshot = testInfo.outputPath("run-detail.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach("run-detail", { path: screenshot, contentType: "image/png" });
});

test("experiment creation runs the pinned dataset and filters traces", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "desktop workflow");
  await page.goto("/experiments");
  await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
  await page.getByRole("button", { name: "Create experiment" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("Name").fill("Playwright experiment");
  await page.getByRole("combobox", { name: "Dataset version" }).selectOption({ label: "Commerce Operations · 1.0.0" });
  await page.getByRole("combobox", { name: "Target version" }).selectOption({ label: "Offline fixture agent · 1.0.0" });
  await page.getByRole("combobox", { name: "Tool contract", exact: true }).selectOption({ label: "default · 1.0.0" });
  await page.getByRole("combobox", { name: "Evaluator set" }).selectOption({ label: "default · 1.0.0" });
  await page.getByRole("button", { name: "Run" }).click();

  const experimentRow = page.getByRole("row").filter({ hasText: "Playwright experiment" });
  await expect(experimentRow).toContainText("3/3", { timeout: 30_000 });
  await expect(experimentRow).toContainText("completed", { ignoreCase: true });
  await experimentRow.getByTitle("View traces").click();
  await expect(page.getByRole("heading", { name: "Traces" })).toBeVisible();
  await expect(page.locator(".page-header p")).toContainText("Experiment exp-");
  await expect(page.getByRole("row")).toHaveCount(4);
});

test("mobile layout keeps the run inspector inside the viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium", "mobile-only visual assertion");
  await page.goto("/traces/trace-listing-launch");
  await expect(page.getByRole("heading", { name: "trace-listing-launch" })).toBeVisible();
  await page.getByRole("tab", { name: "Tools" }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const screenshot = testInfo.outputPath("mobile-run-detail.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  await testInfo.attach("mobile-run-detail", { path: screenshot, contentType: "image/png" });
});
