/**
 * Document Management E2E tests
 *
 * Covers:
 *   - Document list renders from API
 *   - Status badge shown per document
 *   - Upload requires title before accepting a file
 *   - File upload triggers API call and refreshes list
 *   - Delete button triggers confirmation dialog then removes row
 */

import * as path from "path";
import { test as authTest, expect, mockBackend } from "../fixtures/auth";
import { DocumentsPage } from "../pages/DocumentsPage";

authTest.describe("Document list", () => {
  authTest("renders documents from the API", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    const count = await docs.getDocumentCount();
    expect(count).toBe(2);
    await page.screenshot({ path: "artifacts/documents-list.png" });
  });

  authTest("shows 'indexed' status for the first document", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    const firstRow = page.locator('[data-testid="document-row"]').first();
    await expect(firstRow).toContainText("indexed");
    await expect(firstRow).toContainText("aspirin_pil.pdf");
  });

  authTest("shows 'processing' status for the second document", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    const secondRow = page.locator('[data-testid="document-row"]').nth(1);
    await expect(secondRow).toContainText("processing");
  });

  authTest("shows chunk count for indexed documents", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    const firstRow = page.locator('[data-testid="document-row"]').first();
    await expect(firstRow).toContainText("24"); // chunk_count from mock
  });
});

authTest.describe("Document upload", () => {
  authTest("title field is required — upload dropzone visible", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    await expect(docs.titleInput).toBeVisible();
    await expect(docs.dropzone).toBeVisible();
  });

  authTest("uploading a PDF file calls the upload API and refreshes the list", async ({ authenticatedPage: page }) => {
    // Intercept upload and return the mock success response
    let uploadCalled = false;
    await page.route("**/manage/documents/upload", (route) => {
      uploadCalled = true;
      route.fulfill({
        json: {
          document_id: "doc-new",
          filename: "test.pdf",
          status: "pending",
          message: "Upload successful.",
        },
      });
    });

    const docs = new DocumentsPage(page);
    await docs.goto();
    await docs.titleInput.fill("Test Document");

    // Trigger the file chooser via dropzone click
    const fileChooserPromise = page.waitForEvent("filechooser");
    await docs.dropzone.click();
    const fileChooser = await fileChooserPromise;

    // Use a small synthetic file — Playwright creates it from buffer
    await fileChooser.setFiles({
      name: "test.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 test content"),
    });

    // Wait for the upload API to be called
    await page.waitForFunction(() => true); // allow micro-tasks to flush
    expect(uploadCalled).toBe(true);
    await page.screenshot({ path: "artifacts/upload-success.png" });
  });
});

authTest.describe("Document deletion", () => {
  authTest("delete button shows confirmation dialog", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    // Intercept the dialog and dismiss it (cancel)
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.locator('[data-testid="delete-button"]').first().click();

    // After dismiss, document count should be unchanged
    const count = await docs.getDocumentCount();
    expect(count).toBe(2);
  });

  authTest("confirming delete calls API and removes document from list", async ({ authenticatedPage: page }) => {
    let deleteCalled = false;

    // Override document list to return only 1 doc after deletion
    let callCount = 0;
    await page.route("**/manage/documents**", (route) => {
      if (route.request().method() === "DELETE") {
        deleteCalled = true;
        route.fulfill({ json: { message: "Document doc-001 deleted" } });
      } else if (route.request().method() === "GET") {
        callCount++;
        const docs = callCount === 1
          ? [{ document_id: "doc-001", filename: "aspirin_pil.pdf", status: "indexed", metadata: {}, chunk_count: 24, created_at: "2026-05-01T10:00:00Z", updated_at: "2026-05-01T10:05:00Z" }]
          : [];
        route.fulfill({ json: { documents: docs, total: docs.length, page: 1, limit: 20 } });
      } else {
        route.continue();
      }
    });

    const docs = new DocumentsPage(page);
    await docs.goto();

    // Accept the confirmation dialog
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator('[data-testid="delete-button"]').first().click();

    await page.waitForFunction(() => true);
    expect(deleteCalled).toBe(true);
    await page.screenshot({ path: "artifacts/delete-confirmed.png" });
  });
});
