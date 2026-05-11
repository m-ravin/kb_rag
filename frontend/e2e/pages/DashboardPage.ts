import { Page, Locator } from "@playwright/test";

export class DashboardPage {
  readonly sidebar: Locator;
  readonly navDashboard: Locator;
  readonly navDocuments: Locator;
  readonly navQaTest: Locator;
  readonly logoutButton: Locator;
  readonly chart: Locator;
  readonly statTotalQuestions: Locator;
  readonly statAvgLatency: Locator;
  readonly statPiiFlags: Locator;
  readonly statTokens: Locator;
  readonly metricsError: Locator;

  constructor(private page: Page) {
    this.sidebar            = page.locator('[data-testid="sidebar-nav"]');
    this.navDashboard       = page.locator('[data-testid="nav-dashboard"]');
    this.navDocuments       = page.locator('[data-testid="nav-documents"]');
    this.navQaTest          = page.locator('[data-testid="nav-q-a-test"]');
    this.logoutButton       = page.locator('[data-testid="logout-button"]');
    this.chart              = page.locator(".recharts-wrapper");
    this.statTotalQuestions = page.locator('[data-testid="stat-total-questions"]');
    this.statAvgLatency     = page.locator('[data-testid="stat-avg-latency"]');
    this.statPiiFlags       = page.locator('[data-testid="stat-pii-flags"]');
    this.statTokens         = page.locator('[data-testid="stat-tokens"]');
    this.metricsError       = page.locator('[data-testid="metrics-error"]');
  }

  async goto() {
    await this.page.goto("/dashboard");
    await this.page.waitForLoadState("networkidle");
  }
}
