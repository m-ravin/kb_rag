import { Page, Locator, expect } from "@playwright/test";

export class DocumentsPage {
  readonly titleInput: Locator;
  readonly dropzone: Locator;
  readonly documentRows: Locator;

  constructor(private page: Page) {
    this.titleInput    = page.locator('[data-testid="document-title-input"]');
    this.dropzone      = page.locator('[data-testid="upload-dropzone"]');
    this.documentRows  = page.locator('[data-testid="document-row"]');
  }

  async goto() {
    await this.page.goto("/documents");
    await expect(this.dropzone).toBeVisible();
  }

  async uploadFile(filePath: string, title: string) {
    await this.titleInput.fill(title);
    const fileChooserPromise = this.page.waitForEvent("filechooser");
    await this.dropzone.click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(filePath);
  }

  async getDocumentCount(): Promise<number> {
    return this.documentRows.count();
  }

  async deleteFirstDocument() {
    this.page.once("dialog", async (dialog) => dialog.accept());
    await this.documentRows.first().locator('[data-testid="delete-button"]').click({ force: true });
  }
}
