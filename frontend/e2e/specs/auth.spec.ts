/**
 * Auth flow E2E tests
 *
 * Covers:
 *   - Successful login redirects to dashboard
 *   - Wrong password shows error message
 *   - Protected routes redirect unauthenticated users to /login
 *   - Logout clears session and redirects to /login
 */

import { test, expect } from "@playwright/test";
import { LoginPage } from "../pages/LoginPage";
import { mockBackend } from "../fixtures/auth";

test.describe("Authentication", () => {
  test("login with valid credentials redirects to dashboard", async ({ page }) => {
    await mockBackend(page);
    const login = new LoginPage(page);
    await login.goto();

    await login.login("admin@test.com", "correct-password");

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
    await expect(page.locator('[data-testid="sidebar-nav"]')).toBeVisible();
    await page.screenshot({ path: "artifacts/login-success.png" });
  });

  test("wrong password shows inline error message", async ({ page }) => {
    // Override the token endpoint to return 401
    await page.route("**/manage/auth/token", (route) =>
      route.fulfill({ status: 401, json: { detail: "Invalid email or password" } })
    );

    const login = new LoginPage(page);
    await login.goto();
    await login.login("admin@test.com", "wrong-password");

    await login.expectError("Invalid email or password");
    await expect(page).toHaveURL(/\/login/);
    await page.screenshot({ path: "artifacts/login-error.png" });
  });

  test("empty email field prevents form submission", async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto();

    // Click submit without filling email
    await login.passwordInput.fill("somepassword");
    await login.submitButton.click();

    // Browser native validation keeps us on /login
    await expect(page).toHaveURL(/\/login/);
  });

  test("unauthenticated user is redirected from /dashboard to /login", async ({ page }) => {
    // No token in localStorage — navigating directly to a protected route
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/, { timeout: 5_000 });
  });

  test("unauthenticated user is redirected from /documents to /login", async ({ page }) => {
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/login/, { timeout: 5_000 });
  });

  test("unauthenticated user is redirected from /qa-test to /login", async ({ page }) => {
    await page.goto("/qa-test");
    await expect(page).toHaveURL(/\/login/, { timeout: 5_000 });
  });

  test("logout clears session and redirects to /login", async ({ page }) => {
    await mockBackend(page);
    await page.goto("/login");
    await page.evaluate(() =>
      localStorage.setItem(
        "access_token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbkB0ZXN0LmNvbSIsInJvbGUiOiJhZG1pbiJ9.mock"
      )
    );

    await page.goto("/dashboard");
    await page.locator('[data-testid="logout-button"]').click();

    await expect(page).toHaveURL(/\/login/, { timeout: 5_000 });

    // Token must be cleared from localStorage
    const token = await page.evaluate(() => localStorage.getItem("access_token"));
    expect(token).toBeNull();
    await page.screenshot({ path: "artifacts/logout.png" });
  });
});
