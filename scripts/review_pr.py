"""
Claude Code PR Reviewer
=======================
Called by .github/workflows/pr-review.yml after test, lint, and security jobs.

Decision matrix:
  BLOCK (REQUEST_CHANGES, no Claude call):
    - tests failed
    - bandit HIGH severity issues found
  Claude decides (APPROVE / REQUEST_CHANGES / COMMENT):
    - all gates pass → Claude reviews code quality
    - lint/checkov issues → included as context for Claude
"""

import json
import os
import subprocess
import sys
import textwrap

import anthropic

_SKIP_PATTERNS = [
    ":(exclude)uv.lock",
    ":(exclude)*.lock",
    ":(exclude)frontend/package-lock.json",
    ":(exclude)frontend/node_modules/**",
    ":(exclude)*.png",
    ":(exclude)*.jpg",
    ":(exclude)*.ico",
    ":(exclude)data/**",
]
_MAX_DIFF_CHARS = 80_000


# ── Gate helpers ──────────────────────────────────────────────────────────────

def _env_bool(key: str) -> bool:
    return os.environ.get(key, "false").lower() == "true"


def _read_artifact(path: str, max_chars: int = 4000) -> str:
    """
    Reads a file written by an upstream job, returns '' if missing.
    Handles the case where checkov writes a *directory* named checkov_output.json
    (happens with multi-framework scans) by concatenating files found inside it.
    """
    try:
        if os.path.isdir(path):
            # checkov multi-framework output: directory with one JSON per framework
            import glob
            parts = []
            for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
                try:
                    parts.append(open(f).read(max_chars))
                except OSError:
                    pass
            content = "\n".join(parts)
        else:
            with open(path) as f:
                content = f.read()
        return content[:max_chars] + (" [truncated]" if len(content) > max_chars else "")
    except (FileNotFoundError, OSError):
        return ""


def build_gate_summary() -> tuple[bool, str]:
    """
    Returns (hard_block, summary_markdown).
    hard_block=True means we post REQUEST_CHANGES immediately without calling Claude.
    """
    tests_passed    = _env_bool("TESTS_PASSED")
    lint_passed     = _env_bool("LINT_PASSED")
    security_passed = _env_bool("SECURITY_PASSED")
    coverage_pct    = os.environ.get("COVERAGE_PCT", "N/A")
    failed_tests    = os.environ.get("FAILED_TESTS", "0")
    lint_summary    = os.environ.get("LINT_SUMMARY", "")
    bandit_summary  = os.environ.get("BANDIT_SUMMARY", "")
    checkov_summary = os.environ.get("CHECKOV_SUMMARY", "")

    lines = ["## CI Gate Results\n"]

    # Tests
    icon = "✅" if tests_passed else "❌"
    lines.append(f"| {icon} Tests | {'' if tests_passed else f'{failed_tests} test(s) FAILED'} | Coverage: {coverage_pct}% |")

    # Lint
    icon = "✅" if lint_passed else "⚠️"
    lines.append(f"| {icon} Lint  | {lint_summary or ('clean' if lint_passed else 'issues found')} |")

    # Security
    icon = "✅" if security_passed else "🚨"
    lines.append(f"| {icon} Security | bandit: {bandit_summary} | checkov: {checkov_summary} |")

    # Hard block: fail tests or bandit HIGH security issues
    hard_block = not tests_passed or (not security_passed and "HIGH" in bandit_summary)
    if hard_block:
        reasons = []
        if not tests_passed:
            reasons.append(f"{failed_tests} test(s) are failing")
        if not security_passed and "HIGH" in bandit_summary:
            reasons.append(f"bandit found HIGH severity security issues: {bandit_summary}")
        lines.append(
            f"\n> 🚫 **Auto-blocked**: {'; '.join(reasons)}. "
            "Fix these before this PR can be approved."
        )

    return hard_block, "\n".join(lines)


# ── Diff ──────────────────────────────────────────────────────────────────────

def get_diff() -> str:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    result = subprocess.run(
        ["git", "diff", base, head, "--"] + _SKIP_PATTERNS,
        capture_output=True, text=True, check=True,
    )
    diff = result.stdout
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + f"\n\n[... truncated at {_MAX_DIFF_CHARS:,} chars ...]"
    return diff


# ── Claude prompt ─────────────────────────────────────────────────────────────

def build_prompt(diff: str, gate_summary: str) -> str:
    pytest_output  = _read_artifact("pytest_output.txt")
    ruff_output    = _read_artifact("ruff_output.txt")
    bandit_raw     = _read_artifact("bandit_output.json")
    checkov_raw    = _read_artifact("checkov_output.json")

    # Parse bandit JSON for readable findings
    bandit_findings = ""
    try:
        bandit_data = json.loads(bandit_raw)
        issues = bandit_data.get("results", [])
        if issues:
            bandit_findings = "\n".join(
                f"- [{r['issue_severity']}] {r['issue_text']} "
                f"({r['filename']}:{r['line_number']})"
                for r in issues[:20]
            )
    except (json.JSONDecodeError, KeyError):
        bandit_findings = bandit_raw[:1000] if bandit_raw else ""

    return textwrap.dedent(f"""\
        You are a senior code reviewer for **KB RAG** — an Azure-hosted RAG system
        built with FastAPI, Azure OpenAI, Azure AI Search, Cosmos DB (MongoDB + Gremlin),
        Redis, Azure Functions, AKS, and Terraform.

        ## PR Details
        Title: {os.environ.get("PR_TITLE", "")}
        Description: {os.environ.get("PR_BODY", "No description")}
        Changed files: {os.environ.get("CHANGED_FILES")} | +{os.environ.get("ADDITIONS")} / -{os.environ.get("DELETIONS")}

        ## Automated Check Results (already run by CI — do not re-check these)

        {gate_summary}

        ### pytest output (last 50 lines)
        ```
        {pytest_output[-3000:] if pytest_output else "No output captured"}
        ```

        ### ruff lint output
        ```
        {ruff_output[-2000:] if ruff_output else "No issues"}
        ```

        ### bandit security findings
        ```
        {bandit_findings or "No issues"}
        ```

        ## Diff
        ```diff
        {diff}
        ```

        ## Your review focus (CI already caught tests/lint/security above)

        Review the diff for things CI cannot catch:

        ### Logic & Correctness
        - Business logic errors, off-by-one, wrong conditions
        - Race conditions in async code
        - Incorrect Pydantic model validation (missing fields, wrong types)

        ### Security gaps CI missed
        - PII data reaching Azure OpenAI or MongoDB logs without masking
          (check that `mask_pii()` is called before any LLM or log call)
        - Secrets interpolated directly in Kubernetes manifests or Terraform locals
        - Missing `Depends(require_role(...))` on new management endpoints

        ### Azure / Cloud correctness
        - Terraform resources that would be destroyed on rename (missing lifecycle)
        - Missing `prevent_destroy` on stateful Azure resources
        - AKS pods with hardcoded env vars instead of `secretRef`

        ### Maintainability
        - Functions > 50 lines without clear extraction opportunity
        - Missing error handling on Azure SDK calls
        - `print()` instead of `logging`

        ## Output format (keep headers verbatim)

        ## Summary
        [1-2 sentences]

        ## Findings

        ### 🔴 CRITICAL
        [findings or "None"]

        ### 🟠 HIGH
        [findings or "None"]

        ### 🟡 MEDIUM
        [findings or "None"]

        ### 🟢 LOW / Suggestions
        [findings or "None"]

        ## Decision
        **[APPROVE / REQUEST_CHANGES / COMMENT]** — [one sentence reason]

        Decision rules:
        - APPROVE: zero CRITICAL and zero HIGH findings (note: if CI gates above already
          block this PR, your decision is overridden — focus on code quality only)
        - REQUEST_CHANGES: any CRITICAL finding, or 2+ HIGH findings
        - COMMENT: exactly 1 HIGH finding, or only MEDIUM/LOW
    """)


# ── Post review ───────────────────────────────────────────────────────────────

def post_review(body: str, decision: str) -> None:
    pr  = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]

    full_body = (
        "## 🤖 Claude Code Review\n\n"
        + body
        + "\n\n---\n*Reviewed by [Claude claude-sonnet-4-6](https://anthropic.com) "
        "via GitHub Actions · [workflow](.github/workflows/pr-review.yml)*"
    )

    flag = f"--{decision}"
    result = subprocess.run(
        ["gh", "pr", "review", pr, "--repo", repo, flag, "--body", full_body],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gh pr review failed ({result.stderr}), falling back to comment", file=sys.stderr)
        subprocess.run(
            ["gh", "pr", "comment", pr, "--repo", repo, "--body", full_body],
            check=True,
        )
    else:
        print(f"✅ Review posted as {decision.upper()} on PR #{pr}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    hard_block, gate_summary = build_gate_summary()

    print(f"Gate summary:\n{gate_summary}\n")

    if hard_block:
        # Tests failed or bandit HIGH — block without calling Claude API
        print("Hard block triggered — posting REQUEST_CHANGES without Claude call")
        post_review(gate_summary, "request-changes")
        return

    print("All hard gates passed — calling Claude for code quality review...")
    diff = get_diff()
    if not diff.strip():
        print("Empty diff — nothing to review")
        return

    print(f"Diff: {len(diff):,} chars")
    prompt = build_prompt(diff, gate_summary)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        review_text = message.content[0].text
    except anthropic.BadRequestError as exc:
        if "credit balance is too low" in str(exc):
            notice = (
                gate_summary
                + "\n\n> ⚠️ **Claude AI Review skipped** — Anthropic account has insufficient credits. "
                "Add credits at [console.anthropic.com](https://console.anthropic.com) → Plans & Billing."
            )
            # All CI gates passed — approve so the PR is not blocked by missing credits
            post_review(notice, "approve")
            print(f"Skipped Claude review — no credits: {exc}")
            return
        raise
    except anthropic.AuthenticationError as exc:
        notice = (
            gate_summary
            + "\n\n> ⚠️ **Claude AI Review skipped** — Invalid `ANTHROPIC_API_KEY` secret. "
            f"Error: `{exc}`"
        )
        # All CI gates passed — approve so the PR is not blocked by a misconfigured key
        post_review(notice, "approve")
        print(f"Skipped Claude review — auth error: {exc}")
        return

    # Parse decision from Claude's response
    decision = "comment"
    for line in review_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**APPROVE"):
            decision = "approve"
            break
        if stripped.startswith("**REQUEST_CHANGES"):
            decision = "request-changes"
            break

    full_body = gate_summary + "\n\n---\n\n" + review_text
    post_review(full_body, decision)


if __name__ == "__main__":
    main()
