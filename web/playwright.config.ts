import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.EVAL_E2E_URL || "http://127.0.0.1:8770";
const python = process.env.PYTHON_EXECUTABLE || (process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results/artifacts",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"], viewport: { width: 412, height: 915 } } },
  ],
  webServer: {
    command: `"${python}" ../tests/e2e_server.py`,
    url: `${baseURL}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
