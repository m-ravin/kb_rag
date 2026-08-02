import { Page, Locator, expect, FilePayload } from "@playwright/test";

type FileInput = string | FilePayload;

export class DocumentsPage {
  readonly titleInput: Locator;
  readonly dropzone: Locator;
  readonly documentRows: Locator;
  readonly stagedFile: Locator;
  readonly removeStagedFileButton: Locator;
  readonly uploadButton: Locator;

  constructor(private page: Page) {
    this.titleInput             = page.locator('[data-testid="document-title-input"]');
    this.dropzone               = page.locator('[data-testid="upload-dropzone"]');
    this.documentRows           = page.locator('[data-testid="document-row"]');
    this.stagedFile             = page.locator('[data-testid="staged-file"]');
    this.removeStagedFileButton = page.locator('[data-testid="remove-staged-file"]');
    this.uploadButton           = page.locator('[data-testid="upload-button"]');
  }

  async goto() {
    await this.page.goto("/documents");
    await expect(this.dropzone).toBeVisible();
  }

  /** Selects a file via the dropzone without confirming the upload. */
  async selectFile(file: FileInput) {
    const fileChooserPromise = this.page.waitForEvent("filechooser");
    await this.dropzone.click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(file);
    await expect(this.stagedFile).toBeVisible();
  }

  /** Stages a file, fills the title, and clicks Upload to confirm. */
  async uploadFile(file: FileInput, title: string) {
    await this.titleInput.fill(title);
    await this.selectFile(file);
    await this.uploadButton.click();
  }

  async getDocumentCount(): Promise<number> {
    return this.documentRows.count();
  }

  async deleteFirstDocument() {
    this.page.once("dialog", async (dialog) => dialog.accept());
    await this.documentRows.first().locator('[data-testid="delete-button"]').click({ force: true });
  }
}
