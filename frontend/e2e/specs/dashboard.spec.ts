/**
 * Dashboard E2E tests
 *
 * Covers:
 *   - Metric cards render with values from API
 *   - Chart container is present and visible
 *   - Navigation links route to correct pages
 */

import { test as authTest, expect } from "../fixtures/auth";

authTest.describe("Dashboard", () => {
  authTest("renders all four metric stat cards", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // The dashboard renders 4 stat cards — verify at least 2 are visible
    const statCards = page.locator(".grid > div");
    await expect(statCards).toHaveCount(4, { timeout: 8_000 });
    await page.screenshot({ path: "artifacts/dashboard.png" });
  });

  authTest("Total Questions card shows value from API", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // The dashboard fetches metrics and displays total_questions = 142
    await expect(page.getByText("142")).toBeVisible({ timeout: 8_000 });
  });

  authTest("sidebar navigation links are all visible", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");

    await expect(page.locator('[data-testid="nav-dashboard"]')).toBeVisible();
    await expect(page.locator('[data-testid="nav-documents"]')).toBeVisible();
    await expect(page.locator('[data-testid="nav-q-a-test"]')).toBeVisible();
  });

  authTest("clicking Documents nav navigates to /documents", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");
    await page.locator('[data-testid="nav-documents"]').click();
    await expect(page).toHaveURL(/\/documents/);
  });

  authTest("clicking Q&A Test nav navigates to /qa-test", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");
    await page.locator('[data-testid="nav-q-a-test"]').click();
    await expect(page).toHaveURL(/\/qa-test/);
  });

  authTest("bar chart container renders", async ({ authenticatedPage: page }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Recharts renders an SVG inside a div — check it exists
    await expect(page.locator(".recharts-wrapper")).toBeVisible({ timeout: 8_000 });
  });
});
