import { Page, Locator, expect } from "@playwright/test";

export class QAConsolePage {
  readonly questionInput: Locator;
  readonly languageSelect: Locator;
  readonly askButton: Locator;
  readonly answerCard: Locator;
  readonly answerText: Locator;
  readonly sourcesCard: Locator;
  readonly errorMessage: Locator;
  readonly piiBadge: Locator;
  readonly unsafeBadge: Locator;

  constructor(private page: Page) {
    this.questionInput  = page.locator('[data-testid="question-input"]');
    this.languageSelect = page.locator('[data-testid="language-select"]');
    this.askButton      = page.locator('[data-testid="ask-button"]');
    this.answerCard     = page.locator('[data-testid="answer-card"]');
    this.answerText     = page.locator('[data-testid="answer-text"]');
    this.sourcesCard    = page.locator('[data-testid="sources-card"]');
    this.errorMessage   = page.locator('[data-testid="qa-error"]');
    this.piiBadge       = page.locator('[data-testid="pii-badge"]');
    this.unsafeBadge    = page.locator('[data-testid="unsafe-badge"]');
  }

  async goto() {
    await this.page.goto("/qa-test");
    await expect(this.questionInput).toBeVisible();
  }

  async ask(question: string, language = "en") {
    await this.questionInput.fill(question);
    if (language !== "en") {
      await this.languageSelect.selectOption(language);
    }
    await this.askButton.click();
    // Wait for the answer to appear (API call completes)
    await expect(this.answerCard).toBeVisible({ timeout: 15_000 });
  }

  async getAnswerText(): Promise<string> {
    return (await this.answerText.textContent()) ?? "";
  }

  async getSourceCount(): Promise<number> {
    return this.page.locator('[data-testid="source-item"]').count();
  }
}
