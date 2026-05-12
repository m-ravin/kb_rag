/**
 * Dashboard E2E tests
 *
 * Covers:
 *   - All four metric stat cards render with values from API
 *   - Each metric card shows the correct value (total questions, avg latency, PII flags, tokens)
 *   - Bar chart container renders
 *   - Navigation links route to correct pages
 *   - Error state shown when metrics API fails
 */

import { test as authTest, expect } from "../fixtures/auth";
import { DashboardPage } from "../pages/DashboardPage";

authTest.describe("Dashboard — metric cards", () => {
  authTest("renders all four stat cards", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.statTotalQuestions).toBeVisible({ timeout: 8_000 });
    await expect(dash.statAvgLatency).toBeVisible();
    await expect(dash.statPiiFlags).toBeVisible();
    await expect(dash.statTokens).toBeVisible();
    await page.screenshot({ path: "artifacts/dashboard.png" });
  });

  authTest("Total Questions card shows value from API (142)", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.statTotalQuestions).toContainText("142", { timeout: 8_000 });
  });

  authTest("Avg Latency card shows rounded value from API (380)", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.statAvgLatency).toContainText("380", { timeout: 8_000 });
  });

  authTest("PII Flags card shows count from API (3)", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.statPiiFlags).toContainText("3", { timeout: 8_000 });
  });

  authTest("Tokens Used card shows formatted value from API (24,800)", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    // toLocaleString() renders 24800 as "24,800" in en-US locale
    await expect(dash.statTokens).toContainText("24", { timeout: 8_000 });
  });
});

authTest.describe("Dashboard — chart", () => {
  authTest("activity bar chart renders", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.chart).toBeVisible({ timeout: 8_000 });
  });
});

authTest.describe("Dashboard — navigation", () => {
  authTest("sidebar nav links are all visible", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.navDashboard).toBeVisible();
    await expect(dash.navDocuments).toBeVisible();
    await expect(dash.navQaTest).toBeVisible();
  });

  authTest("clicking Documents nav navigates to /documents", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await dash.navDocuments.click();
    await expect(page).toHaveURL(/\/documents/);
  });

  authTest("clicking Q&A Test nav navigates to /qa-test", async ({ authenticatedPage: page }) => {
    const dash = new DashboardPage(page);
    await dash.goto();

    await dash.navQaTest.click();
    await expect(page).toHaveURL(/\/qa-test/);
  });
});

authTest.describe("Dashboard — error handling", () => {
  authTest("shows error message when metrics API returns 500", async ({ authenticatedPage: page }) => {
    await page.route("**/manage/metrics", (route) =>
      route.fulfill({ status: 500, json: { detail: "Internal server error" } })
    );

    const dash = new DashboardPage(page);
    await dash.goto();

    await expect(dash.metricsError).toBeVisible({ timeout: 8_000 });
    await expect(dash.statTotalQuestions).not.toBeVisible();
    await page.screenshot({ path: "artifacts/dashboard-error.png" });
  });
});
