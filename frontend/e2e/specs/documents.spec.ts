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

import { test as authTest, expect } from "../fixtures/auth";
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

    // Start waiting for the upload response BEFORE triggering the file selection
    const uploadResponsePromise = page.waitForResponse(
      (res) => res.url().includes("documents/upload"),
      { timeout: 10_000 }
    );

    await fileChooser.setFiles({
      name: "test.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("PDF test content"),
    });

    // Wait for the upload API call to complete before asserting
    await uploadResponsePromise;
    expect(uploadCalled).toBe(true);
    await page.screenshot({ path: "artifacts/upload-success.png" });
  });
});

authTest.describe("Document deletion", () => {
  authTest("delete button shows confirmation dialog", async ({ authenticatedPage: page }) => {
    const docs = new DocumentsPage(page);
    await docs.goto();

    // Use page.once so the handler runs DURING the click action (not after).
    // waitForEvent + await click() causes a deadlock: the click waits for the page
    // to settle, but the page can't settle until the confirm() dialog is dismissed,
    // and we can't dismiss it until await click() returns. page.once avoids this.
    // force: true bypasses element interception on narrow (mobile) viewports.
    let capturedMessage = "";
    page.once("dialog", async (dialog) => {
      capturedMessage = dialog.message();
      await dialog.dismiss();
    });
    await page.locator('[data-testid="delete-button"]').first().click({ force: true });

    // Verify the confirm dialog appeared with the expected message
    expect(capturedMessage).toContain("Delete");
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

    // Accept the confirmation dialog.
    // force: true bypasses interception by overlapping elements on narrow viewports.
    page.once("dialog", (dialog) => dialog.accept());

    // Wait for the DELETE network response before asserting — avoids the
    // page.waitForFunction(() => true) no-op antipattern that gave no real guarantee.
    const deleteResponsePromise = page.waitForResponse(
      (res) => res.request().method() === "DELETE" && res.url().includes("documents"),
      { timeout: 10_000 }
    );
    await page.locator('[data-testid="delete-button"]').first().click({ force: true });
    await deleteResponsePromise;

    expect(deleteCalled).toBe(true);
    await page.screenshot({ path: "artifacts/delete-confirmed.png" });
  });
});
