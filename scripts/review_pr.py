"""
OpenAI PR Reviewer
==================
Called by .github/workflows/pr-review.yml after test, lint, and security jobs.

Decision matrix:
  BLOCK (REQUEST_CHANGES, no OpenAI call):
    - tests failed
    - bandit HIGH severity issues found
  OpenAI decides (APPROVE / REQUEST_CHANGES / COMMENT):
    - all hard gates pass: review code quality
    - lint/checkov issues: include them as review context
"""

import json
import os
import subprocess
import sys
import textwrap

from openai import APIStatusError, AuthenticationError, OpenAI, RateLimitError

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
_DEFAULT_MODEL = "gpt-5-mini"


def _env_bool(key: str) -> bool:
    return os.environ.get(key, "false").lower() == "true"


def _read_artifact(path: str, max_chars: int = 4000) -> str:
    """
    Read an upstream CI artifact, returning an empty string if it is unavailable.

    Example:
        >>> _read_artifact("missing.txt")
        ''
    """
    try:
        if os.path.isdir(path):
            import glob

            parts = []
            for artifact_path in sorted(
                glob.glob(os.path.join(path, "**", "*.json"), recursive=True)
            ):
                try:
                    with open(artifact_path, encoding="utf-8") as artifact:
                        parts.append(artifact.read(max_chars))
                except OSError:
                    pass
            content = "\n".join(parts)
        else:
            with open(path, encoding="utf-8") as artifact:
                content = artifact.read()
        return content[:max_chars] + (" [truncated]" if len(content) > max_chars else "")
    except (FileNotFoundError, OSError):
        return ""


def build_gate_summary() -> tuple[bool, str]:
    """
    Return whether hard CI gates failed and a Markdown summary for the PR review.

    Example:
        >>> isinstance(build_gate_summary()[0], bool)
        True
    """
    tests_passed = _env_bool("TESTS_PASSED")
    lint_passed = _env_bool("LINT_PASSED")
    security_passed = _env_bool("SECURITY_PASSED")
    coverage_pct = os.environ.get("COVERAGE_PCT", "N/A")
    failed_tests = os.environ.get("FAILED_TESTS", "0")
    lint_summary = os.environ.get("LINT_SUMMARY", "")
    bandit_summary = os.environ.get("BANDIT_SUMMARY", "")
    checkov_summary = os.environ.get("CHECKOV_SUMMARY", "")

    lines = ["## CI Gate Results\n"]
    lines.append(
        f"| {'PASS' if tests_passed else 'FAIL'} Tests | "
        f"{'' if tests_passed else f'{failed_tests} test(s) FAILED'} | "
        f"Coverage: {coverage_pct}% |"
    )
    lines.append(
        f"| {'PASS' if lint_passed else 'WARN'} Lint | "
        f"{lint_summary or ('clean' if lint_passed else 'issues found')} |"
    )
    lines.append(
        f"| {'PASS' if security_passed else 'WARN'} Security | "
        f"bandit: {bandit_summary} | checkov: {checkov_summary} |"
    )

    hard_block = not tests_passed or (not security_passed and "HIGH" in bandit_summary)
    if hard_block:
        reasons = []
        if not tests_passed:
            reasons.append(f"{failed_tests} test(s) are failing")
        if not security_passed and "HIGH" in bandit_summary:
            reasons.append(f"bandit found HIGH severity security issues: {bandit_summary}")
        lines.append(
            f"\n> **Auto-blocked**: {'; '.join(reasons)}. Fix these before this PR can be approved."
        )

    return hard_block, "\n".join(lines)


def get_diff() -> str:
    """
    Return the PR diff, excluding generated and binary-heavy files.

    Example:
        get_diff()
    """
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
        diff = diff[:_MAX_DIFF_CHARS] + f"\n\n[... truncated at {_MAX_DIFF_CHARS:,} chars ...]"
    return diff


def build_prompt(diff: str, gate_summary: str) -> str:
    """
    Build the code-review prompt sent to OpenAI.

    Example:
        >>> "## Diff" in build_prompt("diff --git a/x b/x", "gates")
        True
    """
    pytest_output = _read_artifact("pytest_output.txt")
    ruff_output = _read_artifact("ruff_output.txt")
    bandit_raw = _read_artifact("bandit_output.json")
    checkov_raw = _read_artifact("checkov_output.json")

    bandit_findings = ""
    try:
        bandit_data = json.loads(bandit_raw)
        issues = bandit_data.get("results", [])
        if issues:
            bandit_findings = "\n".join(
                f"- [{result['issue_severity']}] {result['issue_text']} "
                f"({result['filename']}:{result['line_number']})"
                for result in issues[:20]
            )
    except (json.JSONDecodeError, KeyError):
        bandit_findings = bandit_raw[:1000] if bandit_raw else ""

    return textwrap.dedent(
        f"""\
        You are a senior code reviewer for KB RAG, an Azure-hosted RAG system
        built with FastAPI, Azure OpenAI, Azure AI Search, Cosmos DB, Redis,
        Azure Functions, AKS, and Terraform.

        ## PR Details
        Title: {os.environ.get("PR_TITLE", "")}
        Description: {os.environ.get("PR_BODY", "No description")}
        Changed files: {os.environ.get("CHANGED_FILES")} | +{os.environ.get("ADDITIONS")} / -{os.environ.get("DELETIONS")}

        ## Automated Check Results
        CI already ran these checks. Do not re-check them; use them as context.

        {gate_summary}

        ### pytest output
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

        ### checkov output
        ```
        {checkov_raw[-2000:] if checkov_raw else "No issues"}
        ```

        ## Diff
        ```diff
        {diff}
        ```

        ## Your review focus
        Review the diff for issues CI cannot catch:
        - Logic errors, incorrect conditions, data loss, and edge cases
        - Race conditions in async code
        - Incorrect Pydantic validation
        - PII reaching Azure OpenAI or logs without masking
        - Secrets exposed in Terraform, Kubernetes, or GitHub Actions
        - Missing authorization on management endpoints
        - Azure resource changes that could destroy stateful infrastructure
        - Missing error handling around Azure SDK calls
        - Maintainability problems that create real risk

        ## Output format
        Keep these headers verbatim.

        ## Summary
        [1-2 sentences]

        ## Findings

        ### CRITICAL
        [findings or "None"]

        ### HIGH
        [findings or "None"]

        ### MEDIUM
        [findings or "None"]

        ### LOW / Suggestions
        [findings or "None"]

        ## Decision
        **[APPROVE / REQUEST_CHANGES / COMMENT]** - [one sentence reason]

        Decision rules:
        - APPROVE: zero CRITICAL and zero HIGH findings
        - REQUEST_CHANGES: any CRITICAL finding, or 2+ HIGH findings
        - COMMENT: exactly 1 HIGH finding, or only MEDIUM/LOW
        """
    )


def post_review(body: str, decision: str) -> None:
    """
    Post a GitHub PR review, falling back to a comment if review creation fails.

    Example:
        post_review("Looks good", "comment")
    """
    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["REPO"]
    model = os.environ.get("OPENAI_REVIEW_MODEL", _DEFAULT_MODEL)

    full_body = (
        "## OpenAI Code Review\n\n" + body + "\n\n---\n"
        f"*Reviewed by OpenAI `{model}` via GitHub Actions - "
        "[workflow](.github/workflows/pr-review.yml)*"
    )

    result = subprocess.run(
        ["gh", "pr", "review", pr_number, "--repo", repo, f"--{decision}", "--body", full_body],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"gh pr review failed ({result.stderr}), falling back to comment", file=sys.stderr)
        subprocess.run(
            ["gh", "pr", "comment", pr_number, "--repo", repo, "--body", full_body],
            check=True,
        )
    else:
        print(f"Review posted as {decision.upper()} on PR #{pr_number}")


def run_openai_review(prompt: str) -> str:
    """
    Ask OpenAI for a code review and return the generated Markdown.

    Example:
        run_openai_review("Review this diff")
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.environ.get("OPENAI_REVIEW_MODEL", _DEFAULT_MODEL)

    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=4096,
    )
    return response.output_text


def _build_skipped_notice(gate_summary: str, reason: str) -> str:
    return (
        gate_summary + f"\n\n> **OpenAI Code Review skipped** - {reason}. "
        "The CI hard gates passed, so this automation is approving to avoid blocking the PR "
        "on reviewer configuration."
    )


def main() -> None:
    hard_block, gate_summary = build_gate_summary()
    print(f"Gate summary:\n{gate_summary}\n")

    if hard_block:
        print("Hard block triggered - posting REQUEST_CHANGES without OpenAI call")
        post_review(gate_summary, "request-changes")
        return

    print("All hard gates passed - calling OpenAI for code quality review...")
    diff = get_diff()
    if not diff.strip():
        print("Empty diff - nothing to review")
        return

    print(f"Diff: {len(diff):,} chars")
    prompt = build_prompt(diff, gate_summary)

    try:
        review_text = run_openai_review(prompt)
    except AuthenticationError as exc:
        post_review(
            _build_skipped_notice(gate_summary, f"invalid `OPENAI_API_KEY` secret: `{exc}`"),
            "approve",
        )
        print(f"Skipped OpenAI review - auth error: {exc}")
        return
    except RateLimitError as exc:
        post_review(
            _build_skipped_notice(gate_summary, f"OpenAI quota or rate limit issue: `{exc}`"),
            "approve",
        )
        print(f"Skipped OpenAI review - rate limit/quota error: {exc}")
        return
    except APIStatusError as exc:
        if exc.status_code in {400, 404} and "model" in str(exc).lower():
            reason = (
                "model configuration failed. Set `OPENAI_REVIEW_MODEL` to a model "
                f"available to this OpenAI project. Error: `{exc}`"
            )
            post_review(_build_skipped_notice(gate_summary, reason), "approve")
            print(f"Skipped OpenAI review - model error: {exc}")
            return
        raise

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
