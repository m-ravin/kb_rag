/**
 * Q&A Console E2E tests
 *
 * Covers:
 *   - Ask a question → answer displayed with sources
 *   - Language selector changes the request language
 *   - Ask button disabled when question is empty
 *   - PII badge shown when response.flagged_pii is true
 *   - Error message shown when API fails
 *   - Markdown answer text renders as structured HTML, not raw syntax
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

authTest.describe("Q&A Console — content flags", () => {
  authTest("PII badge appears when response flags PII", async ({ authenticatedPage: page }) => {
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
    await expect(qa.unsafeBadge).not.toBeVisible();
    await page.screenshot({ path: "artifacts/qa-pii-badge.png" });
  });

  authTest("unsafe badge appears when response flags unsafe content", async ({ authenticatedPage: page }) => {
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        json: {
          session_id: "s2",
          question: "How do I overdose on paracetamol?",
          answer: "I cannot assist with that.",
          question_type: "faq",
          sources: [],
          language: "en",
          tokens_used: 30,
          latency_ms: 150,
          flagged_pii: false,
          flagged_unsafe: true,
          created_at: new Date().toISOString(),
        },
      })
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("How do I overdose on paracetamol?");

    await expect(qa.unsafeBadge).toBeVisible();
    await expect(qa.piiBadge).not.toBeVisible();
    await page.screenshot({ path: "artifacts/qa-unsafe-badge.png" });
  });

  authTest("both badges shown when PII and unsafe are flagged simultaneously", async ({ authenticatedPage: page }) => {
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        json: {
          session_id: "s3",
          question: "john@test.com — how to overdose?",
          answer: "I cannot assist with that.",
          question_type: "faq",
          sources: [],
          language: "en",
          tokens_used: 30,
          latency_ms: 150,
          flagged_pii: true,
          flagged_unsafe: true,
          created_at: new Date().toISOString(),
        },
      })
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("john@test.com — how to overdose?");

    await expect(qa.piiBadge).toBeVisible();
    await expect(qa.unsafeBadge).toBeVisible();
  });
});

authTest.describe("Q&A Console — answer formatting", () => {
  authTest("bold text and headings render as real HTML, not raw markdown syntax", async ({ authenticatedPage: page }) => {
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        json: {
          session_id: "s-md-1",
          question: "provide a best receipe for making a cake",
          answer:
            "I don't have enough information to answer this question directly.\n\n" +
            "**Closest match based on available information:**\n" +
            "The knowledge base contains a recipe for **Brownie in a Mug**, a related baked dessert.",
          question_type: "procedural",
          sources: [
            {
              chunk_id: "doc-003_chunk_0",
              document_id: "doc-003",
              filename: "Cooking-Made-Easy.pdf",
              content: "Brownie in a mug: combine flour, cocoa, sugar...",
              score: 0.0331,
            },
          ],
          language: "en",
          tokens_used: 210,
          latency_ms: 300,
          flagged_pii: false,
          flagged_unsafe: false,
          created_at: new Date().toISOString(),
        },
      })
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("provide a best receipe for making a cake");

    // The rendered answer must not contain literal markdown syntax...
    const rawText = await qa.getAnswerText();
    expect(rawText).not.toContain("**");

    // ...and the bold heading must be a real <strong> element.
    const heading = qa.answerText.locator("strong", { hasText: "Closest match based on available information:" });
    await expect(heading).toBeVisible();
  });

  authTest("bulleted answer content renders as a real list, not dash-prefixed text", async ({ authenticatedPage: page }) => {
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        json: {
          session_id: "s-md-2",
          question: "How do I prepare the brownie in a mug?",
          answer:
            "**Closest match based on available information:**\n" +
            "- Combine flour, cocoa powder, sugar\n" +
            "- Add milk and oil, mix well\n" +
            "- Microwave for 90 seconds",
          question_type: "procedural",
          sources: [],
          language: "en",
          tokens_used: 180,
          latency_ms: 250,
          flagged_pii: false,
          flagged_unsafe: false,
          created_at: new Date().toISOString(),
        },
      })
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.ask("How do I prepare the brownie in a mug?");

    const rawText = await qa.getAnswerText();
    expect(rawText).not.toContain("- Combine flour");

    const listItems = qa.answerText.locator("li");
    await expect(listItems).toHaveCount(3);
    await expect(listItems.first()).toContainText("Combine flour, cocoa powder, sugar");
  });
});

test.describe("Q&A Console — error handling", () => {
  test("shows the backend's actual error detail when API returns 500", async ({ page }) => {
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

    const errorEl = page.locator('[data-testid="qa-error"]');
    await expect(errorEl).toBeVisible({ timeout: 10_000 });
    await expect(errorEl).toContainText("Internal error");
    await page.screenshot({ path: "artifacts/qa-error.png" });
  });

  test("shows the dependency's detail message on a 503 (e.g. PII service cold start)", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/qa/ask", (route) =>
      route.fulfill({
        status: 503,
        json: { detail: "PII screening service temporarily unavailable. Please try again shortly." },
      })
    );

    await page.goto("/login");
    await page.evaluate(() =>
      localStorage.setItem("access_token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0IiwicmxlIjoiYWRtaW4ifQ.mock")
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.questionInput.fill("What are the side effects?");
    await qa.askButton.click();

    const errorEl = page.locator('[data-testid="qa-error"]');
    await expect(errorEl).toBeVisible({ timeout: 10_000 });
    await expect(errorEl).toContainText("PII screening service temporarily unavailable");
  });

  test("shows a connection-specific message when the request never reaches the server", async ({ page }) => {
    await mockBackend(page);
    await page.route("**/qa/ask", (route) => route.abort("connectionfailed"));

    await page.goto("/login");
    await page.evaluate(() =>
      localStorage.setItem("access_token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0IiwicmxlIjoiYWRtaW4ifQ.mock")
    );

    const qa = new QAConsolePage(page);
    await qa.goto();
    await qa.questionInput.fill("What are the side effects?");
    await qa.askButton.click();

    const errorEl = page.locator('[data-testid="qa-error"]');
    await expect(errorEl).toBeVisible({ timeout: 10_000 });
    await expect(errorEl).toContainText("Could not reach the server");
  });
});
