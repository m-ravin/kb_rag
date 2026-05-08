/**
 * Auth fixture — injects a valid JWT into localStorage so tests
 * start already logged in without hitting the real login endpoint.
 *
 * Usage:
 *   import { test } from '../fixtures/auth'
 *   test('my test', async ({ authenticatedPage }) => { ... })
 */

import { test as base, Page } from "@playwright/test";

const MOCK_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbkB0ZXN0LmNvbSIsInJvbGUiOiJhZG1pbiJ9.mock";

/** Intercepts all /api/* calls so tests run without a real backend. */
export async function mockBackend(page: Page) {
  // Auth
  await page.route("**/manage/auth/token", (route) =>
    route.fulfill({ json: { access_token: MOCK_TOKEN, token_type: "bearer" } })
  );

  // Metrics / dashboard
  await page.route("**/manage/metrics", (route) =>
    route.fulfill({
      json: {
        total_questions: 142,
        avg_latency_ms: 380,
        total_tokens: 24800,
        pii_flagged_count: 3,
        unsafe_flagged_count: 1,
      },
    })
  );

  // Document list
  await page.route("**/manage/documents**", async (route) => {
    if (route.request().method() === "GET") {
      route.fulfill({
        json: {
          documents: [
            {
              document_id: "doc-001",
              filename: "aspirin_pil.pdf",
              status: "indexed",
              metadata: {},
              chunk_count: 24,
              created_at: "2026-05-01T10:00:00Z",
              updated_at: "2026-05-01T10:05:00Z",
            },
            {
              document_id: "doc-002",
              filename: "ibuprofen_pil.docx",
              status: "processing",
              metadata: {},
              chunk_count: 0,
              created_at: "2026-05-07T09:00:00Z",
              updated_at: "2026-05-07T09:01:00Z",
            },
          ],
          total: 2,
          page: 1,
          limit: 20,
        },
      });
    } else if (route.request().method() === "POST") {
      route.fulfill({
        json: { document_id: "doc-new", filename: "test.pdf", status: "pending", message: "Upload successful." },
      });
    } else if (route.request().method() === "DELETE") {
      route.fulfill({ json: { message: "Document deleted" } });
    } else {
      route.continue();
    }
  });

  // Q&A
  await page.route("**/qa/ask", (route) =>
    route.fulfill({
      json: {
        session_id: "sess-test-001",
        question: "What is the recommended dose?",
        answer: "The recommended adult dose is 500mg every 4-6 hours, not exceeding 4g in 24 hours.",
        question_type: "faq",
        sources: [
          {
            chunk_id: "doc-001_chunk_0",
            document_id: "doc-001",
            filename: "aspirin_pil.pdf",
            content: "Adults: 500mg every 4-6 hours. Maximum 4g per day.",
            score: 0.94,
          },
        ],
        language: "en",
        tokens_used: 320,
        latency_ms: 412.5,
        flagged_pii: false,
        flagged_unsafe: false,
        created_at: new Date().toISOString(),
      },
    })
  );
}

type Fixtures = {
  authenticatedPage: Page;
};

export const test = base.extend<Fixtures>({
  authenticatedPage: async ({ page }, use) => {
    await mockBackend(page);

    // Navigate first so localStorage is scoped to the right origin
    await page.goto("/login");
    await page.evaluate((token) => localStorage.setItem("access_token", token), MOCK_TOKEN);

    await use(page);
  },
});

export { expect } from "@playwright/test";
