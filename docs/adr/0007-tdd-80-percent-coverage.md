# ADR-0007: TDD Workflow with 80% Coverage Threshold Enforced by CI

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The KB RAG system handles healthcare-adjacent data — patient medication queries, PII detection, and medical compliance checking. Bugs in safety-critical paths (PII detection misses, content safety bypasses, chunk loss during indexing) have direct patient impact. The system was initially built end-to-end before tests were written. The TDD workflow was adopted when `/tdd-workflow` was invoked, and immediately found two real bugs: the chunker silently dropped single-word documents (e.g., a drug name alone on a line), and the PII detector missed the Malaysian NRIC format — a critical gap for a system used in a healthcare context.

## Decision

We follow a **Test-Driven Development workflow** for all production code changes, with a minimum of **80% line and branch coverage** enforced by `pytest-cov` in CI. Tests are written before implementation (RED), implementation makes tests pass (GREEN), then code is refactored while keeping tests green (REFACTOR). Coverage is configured in `pyproject.toml` under `[tool.coverage.report]` with `fail_under = 80`. The GitHub Actions deploy workflow runs the full test suite before building Docker images; a coverage failure blocks deployment.

## Alternatives Considered

### Alternative 1: Coverage optional — ship fast, test later
- **Pros**: Faster initial development velocity; no test infrastructure to set up; teams can iterate on product direction before investing in tests
- **Cons**: "Test later" reliably becomes "test never" under delivery pressure; bugs accumulate silently; refactoring becomes risky without a safety net; new engineers cannot verify their changes don't break existing behaviour
- **Why not**: This project demonstrated the cost of this approach during the TDD session: two bugs were found *immediately* upon writing the first tests — bugs that had existed in the codebase since initial implementation. In a healthcare context, an undetected PII miss is a compliance incident.

### Alternative 2: 100% coverage requirement
- **Pros**: Maximum confidence; no uncovered code paths; forces engineers to think about all branches
- **Cons**: The last 20% of coverage is disproportionately expensive — it requires testing error handlers for Azure SDK outages, OS-level exceptions, and timeout scenarios that require elaborate mock setups; creates perverse incentives to write trivial tests rather than meaningful ones; slows iteration
- **Why not**: 100% coverage is associated with diminishing returns and test suite brittleness. The Azure SDK call paths, Gremlin graph traversal internals, and Docker-specific configurations are not worth the mocking overhead. 80% with meaningful tests for business logic is more valuable than 100% with hollow tests for configuration code.

### Alternative 3: Test-after development (write all code, then all tests)
- **Pros**: Developers can move quickly during exploratory phases; tests confirm existing behaviour rather than driving design
- **Cons**: Tests written after the fact tend to test the implementation, not the specification; bugs already present in the implementation are "tested in" rather than caught; test coverage naturally gaps around the code paths that were hardest to write (which are usually the highest-risk paths)
- **Why not**: The TDD session proved that test-first catches bugs that test-after misses. The chunker's `< 20 char` threshold was a deliberate design choice that turned out to be wrong — a test written before the implementation would have forced the question "should a single drug name produce a chunk?" before the bug was baked in.

## Consequences

### Positive
- Two real bugs found and fixed before deployment: chunker short-content drop and missing NRIC PII pattern
- Test suite acts as executable specification — new developers can understand system behaviour by reading tests
- CI gate prevents coverage regression: adding a feature without tests fails the build
- `pytest -v` output serves as living documentation of supported behaviours
- Mocking strategy (all Azure SDK calls mocked in `conftest.py`) means tests run in <5 seconds with no Azure credentials

### Negative
- Initial overhead: setting up `conftest.py` fixtures and mock patterns takes 2–4 hours for a new project
- Azure SDK mock maintenance: when Azure SDK APIs change (e.g., new `SearchClient` method signatures), mocks must be updated
- Some paths genuinely cannot be unit-tested without integration infrastructure (Gremlin graph traversal, blob trigger firing) — these require separate integration test environments

### Risks
- **80% threshold gaming**: Engineers may write low-value tests targeting easy-to-cover lines rather than hard-to-cover business logic branches. Mitigation: code review checks that new tests assert meaningful behaviour, not just that functions return without raising.
- **Mock drift**: If mocked Azure SDK behaviours diverge from actual SDK behaviour (e.g., a method renamed in a minor version), tests pass but the real system fails. Mitigation: integration test suite (separate from unit suite) runs against real Azure resources in the staging environment on a nightly schedule.
