"""
Claude Code PR Reviewer
=======================
Called by .github/workflows/pr-review.yml on every pull_request event.

Flow:
  1. Gets the PR diff (excluding lock files and generated assets)
  2. Sends diff + project context to Claude claude-sonnet-4-6
  3. Parses severity findings from the structured response
  4. Posts the review via `gh pr review` (approve / request-changes / comment)

Required env vars (all injected by the workflow):
  ANTHROPIC_API_KEY, GH_TOKEN, PR_NUMBER, REPO,
  BASE_SHA, HEAD_SHA, PR_TITLE, PR_BODY,
  CHANGED_FILES, ADDITIONS, DELETIONS
"""

import os
import subprocess
import sys
import textwrap

import anthropic

# Files that add noise without useful review signal
_SKIP_PATTERNS = [
    ":(exclude)uv.lock",
    ":(exclude)*.lock",
    ":(exclude)frontend/package-lock.json",
    ":(exclude)frontend/node_modules/**",
    ":(exclude)data/**",
    ":(exclude)*.png",
    ":(exclude)*.jpg",
    ":(exclude)*.ico",
]

# Rough character limit for the diff sent to Claude.
# claude-sonnet-4-6 has a 200k token context window; 80k chars ≈ 20k tokens,
# leaving ample room for the system prompt and the review response.
_MAX_DIFF_CHARS = 80_000


def get_diff() -> str:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]

    result = subprocess.run(
        ["git", "diff", base, head, "--"] + _SKIP_PATTERNS,
        capture_output=True,
        text=True,
        check=True,
    )
    diff = result.stdout

    if len(diff) > _MAX_DIFF_CHARS:
        truncation_note = (
            f"\n\n[... diff truncated at {_MAX_DIFF_CHARS:,} chars "
            f"({len(diff):,} total). Review largest files manually. ...]"
        )
        return diff[:_MAX_DIFF_CHARS] + truncation_note

    return diff


def build_prompt(diff: str) -> str:
    pr_title = os.environ.get("PR_TITLE", "")
    pr_body = os.environ.get("PR_BODY", "No description provided.")
    changed_files = os.environ.get("CHANGED_FILES", "?")
    additions = os.environ.get("ADDITIONS", "?")
    deletions = os.environ.get("DELETIONS", "?")

    return textwrap.dedent(f"""\
        You are a senior code reviewer for **KB RAG** — an Azure-hosted,
        end-to-end Retrieval-Augmented Generation system built with:
          - FastAPI + Python 3.11 (async/await throughout)
          - Azure OpenAI (GPT-4o + text-embedding-3-small)
          - Azure AI Search (hybrid vector + BM25 search)
          - Azure Cosmos DB (MongoDB API for metadata, Gremlin API for graphs)
          - Azure Cache for Redis (search result caching)
          - Azure Functions (blob-triggered document processing)
          - Azure Kubernetes Service (AKS) with Key Vault CSI driver
          - Terraform (modular IaC for 15 Azure resources)
          - React + TypeScript (CMS frontend)

        ## Pull Request

        **Title**: {pr_title}
        **Description**: {pr_body}
        **Stats**: {changed_files} files changed, +{additions} / -{deletions}

        ## Diff

        ```diff
        {diff}
        ```

        ## Review Instructions

        Evaluate the changes against these project standards:

        ### Security (CRITICAL / HIGH)
        - PII data sent to Azure OpenAI or stored in logs without masking
          (the project uses `mask_pii()` in safety_service.py — check it is called)
        - Hardcoded credentials, API keys, or connection strings
        - Missing JWT auth on management endpoints
        - Unvalidated user input reaching database queries or file paths
        - Sensitive data in Terraform outputs without `sensitive = true`
        - Secrets referenced in K8s manifests instead of Key Vault

        ### Code Quality (HIGH / MEDIUM)
        - Async functions called without `await`
        - Bare `except:` or swallowed exceptions without logging
        - Functions exceeding 50 lines
        - Files exceeding 800 lines
        - Nesting depth > 4 levels (use early returns instead)
        - Missing Pydantic validation on new API request/response models
        - `print()` statements instead of `logging`

        ### Azure / Cloud (HIGH / MEDIUM)
        - Terraform resources that would be destroyed and recreated on rename
          (use `terraform state mv` instead)
        - Missing `prevent_destroy` lifecycle on stateful resources
          (Cosmos DB, Key Vault, Storage)
        - AKS workloads reading secrets from env literals instead of K8s Secret refs
        - Azure Function timeout risks for large document processing jobs

        ### Testing (MEDIUM / LOW)
        - New business logic without corresponding tests
        - Tests that only assert no exception is raised (not meaningful)
        - Mocks that don't reflect real Azure SDK call signatures

        ### Style (LOW)
        - Inconsistent naming conventions
        - Missing docstrings on public API functions
        - Commented-out code left in

        ## Output Format

        Respond with EXACTLY this structure (keep section headers verbatim):

        ## Summary
        [1-2 sentences: overall quality and main concern]

        ## Findings

        ### 🔴 CRITICAL
        [Bullet list with file:line references, or write "None"]

        ### 🟠 HIGH
        [Bullet list with file:line references, or write "None"]

        ### 🟡 MEDIUM
        [Bullet list with file:line references, or write "None"]

        ### 🟢 LOW / Suggestions
        [Bullet list, or write "None"]

        ## Decision
        **[APPROVE / REQUEST_CHANGES / COMMENT]** — [one sentence justification]

        Rules for decision:
        - APPROVE: zero CRITICAL and zero HIGH findings
        - REQUEST_CHANGES: any CRITICAL finding, or two or more HIGH findings
        - COMMENT: exactly one HIGH finding, or only MEDIUM/LOW findings
    """)


def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def parse_decision(review_text: str) -> str:
    """Extracts APPROVE / REQUEST_CHANGES / COMMENT from the review."""
    for line in review_text.splitlines():
        if line.startswith("**APPROVE"):
            return "approve"
        if line.startswith("**REQUEST_CHANGES"):
            return "request-changes"
        if line.startswith("**COMMENT"):
            return "comment"
    return "comment"


def has_critical_findings(review_text: str) -> bool:
    """Returns True if the CRITICAL section has real findings (not 'None')."""
    try:
        section = review_text.split("### 🔴 CRITICAL")[1].split("###")[0].strip()
        return section.lower() != "none" and len(section) > 4
    except IndexError:
        return False


def post_review(review_text: str, decision: str) -> None:
    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]

    body = (
        "## 🤖 Claude Code Review\n\n"
        + review_text
        + "\n\n---\n*Reviewed by [Claude claude-sonnet-4-6](https://anthropic.com) via GitHub Actions*"
    )

    flag = f"--{decision}"

    result = subprocess.run(
        ["gh", "pr", "review", pr_number, "--repo", repo, flag, "--body", body],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"gh pr review failed:\n{result.stderr}", file=sys.stderr)
        # Fall back to a plain comment so the review is never silently lost
        subprocess.run(
            ["gh", "pr", "comment", pr_number, "--repo", repo, "--body", body],
            check=True,
        )
    else:
        print(f"Review posted ({decision}) on PR #{pr_number}")


def main() -> None:
    print("Fetching PR diff...")
    diff = get_diff()

    if not diff.strip():
        print("Empty diff — nothing to review.")
        return

    print(f"Diff size: {len(diff):,} chars. Calling Claude...")
    prompt = build_prompt(diff)
    review_text = call_claude(prompt)

    decision = parse_decision(review_text)
    print(f"Decision: {decision.upper()}")

    post_review(review_text, decision)


if __name__ == "__main__":
    main()
