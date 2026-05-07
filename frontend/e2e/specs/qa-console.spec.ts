/**
 * Q&A Console E2E tests
 *
 * Covers:
 *   - Ask a question → answer displayed with sources
 *   - Language selector changes the request language
 *   - Ask button disabled when question is empty
 *   - PII badge shown when response.flagged_pii is true
 *   - Error message shown when API fails
 */

import { test, expect } from "@playwright/test";
import { QAConsolePage } from "../pages/QAConsolePage";
import { test as authTest, mockBackend } from "../fixtures/auth";

authTest.describe("Q&A Console — happy path", () => {
  authTest("ask a question and receive an answer with sources", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    await qa.ask("What is the recommended dose?");

    const answer = await qa.getAnswerText();
    expect(answer.length).toBeGreaterThan(10);

    const sourceCount = await qa.getSourceCount();
    expect(sourceCount).toBeGreaterThan(0);

    await page.screenshot({ path: "artifacts/qa-answer.png" });
  });

  authTest("sources card shows filename and relevance score", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("What is the recommended dose?");

    await expect(qa.sourcesCard).toBeVisible();
    const firstSource = page.locator('[data-testid="source-item"]').first();
    await expect(firstSource).toContainText("aspirin_pil.pdf");
    await expect(firstSource).toContainText("Score:");
  });

  authTest("language selector defaults to English", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    const selected = await qa.languageSelect.inputValue();
    expect(selected).toBe("en");
  });

  authTest("language can be changed to Bahasa Malaysia", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    await qa.languageSelect.selectOption("ms");
    const selected = await qa.languageSelect.inputValue();
    expect(selected).toBe("ms");
  });
});

authTest.describe("Q&A Console — Ask button states", () => {
  authTest("ask button is disabled when question field is empty", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    await expect(qa.askButton).toBeDisabled();
  });

  authTest("ask button becomes enabled when text is typed", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    await qa.questionInput.fill("What are the side effects?");
    await expect(qa.askButton).toBeEnabled();
  });

  authTest("ask button disabled again after clearing input", async ({ authenticatedPage: page }) => {
    const qa = new QAConsolePage(page);
    await qa.goto();

    await qa.questionInput.fill("Some question");
    await qa.questionInput.fill("");
    await expect(qa.askButton).toBeDisabled();
  });
});

authTest.describe("Q&A Console — PII detection", () => {
  authTest("PII badge appears when response flags PII", async ({ authenticatedPage: page }) => {
    // Override Q&A endpoint to return flagged_pii = true
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        json: {
          session_id: "s1",
          question: "john@test.com — what is the dose?",
          answer: "The dose is 500mg.",
          question_type: "faq",
          sources: [],
          language: "en",
          tokens_used: 50,
          latency_ms: 200,
          flagged_pii: true,
          flagged_unsafe: false,
          created_at: new Date().toISOString(),
        },
      })
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("john@test.com — what is the dose?");

    await expect(qa.piiBadge).toBeVisible();
    await page.screenshot({ path: "artifacts/qa-pii-badge.png" });
  });
});

test.describe("Q&A Console — error handling", () => {
  test("shows error message when API returns 500", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/qa/ask", (route) =>
      route.fulfill({ status: 500, json: { detail: "Internal error" } })
    );

    await page.goto("/login");
    await page.evaluate(() =>
      localStorage.setItem("access_token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0IiwicmxlIjoiYWRtaW4ifQ.mock")
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.questionInput.fill("What are the side effects?");
    await qa.askButton.click();

    await expect(page.locator('[data-testid="qa-error"]')).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "artifacts/qa-error.png" });
  });
});
