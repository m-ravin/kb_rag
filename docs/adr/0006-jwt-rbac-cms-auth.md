# ADR-0006: JWT + Role-Based Access Control for CMS Authentication

**Date**: 2026-05-07
**Status**: accepted
**Deciders**: KB RAG system design

## Context

The Knowledge Management CMS requires authentication and authorisation for document upload, deletion, and user management operations. The system has three distinct permission levels: **admin** (full access including user management), **editor** (upload and modify documents), and **viewer** (read-only metrics and document list). The CMS is used by a small team (5–20 users) and must integrate with the FastAPI backend without requiring an external identity provider dependency in the development environment.

## Decision

We use **JWT (JSON Web Tokens) with role-based access control** implemented in `backend/core/auth.py`. Passwords are hashed with bcrypt via `passlib`. User records (email, hashed password, role) are stored in Cosmos MongoDB. The `/manage/auth/token` endpoint issues a JWT containing the user's email and role, valid for 8 hours. All protected endpoints use FastAPI's `Depends(get_current_user)` or `Depends(require_role("admin"))` dependency injection.

## Alternatives Considered

### Alternative 1: Azure Active Directory / Microsoft Entra ID
- **Pros**: Enterprise-grade identity; SSO with Microsoft 365; MFA built in; no password storage in our system; industry standard for Azure-hosted applications; audit logs in Azure AD
- **Cons**: Requires an Azure AD tenant and app registration; developers need Azure AD accounts to run tests locally; adds external network dependency to the authentication flow; significantly more complex to configure (OAuth2 scopes, redirect URIs, app roles vs tenant roles); overkill for a small internal team
- **Why not**: For a system used by 5–20 internal users, the operational complexity of Azure AD outweighs its benefits. The self-contained JWT approach allows the full system to run locally with `docker-compose up` without any external dependencies. Azure AD can be added later via an `azure-ad` authentication backend if the organisation requires SSO.

### Alternative 2: API key authentication (no user accounts)
- **Pros**: Simplest possible implementation — one header check; stateless; no user database needed; easy to rotate
- **Cons**: Shared API keys cannot attribute actions to specific users (no audit trail); cannot revoke access for a single user without regenerating all keys; no fine-grained permissions (all-or-nothing access)
- **Why not**: The activity log requirement (`POST /manage/activity-logs`) explicitly attributes every action to a named user for audit purposes. Shared API keys make this impossible. The RBAC requirement (admin vs editor vs viewer) also cannot be expressed with flat API keys.

### Alternative 3: Session-based authentication (server-side sessions in Redis)
- **Pros**: Sessions can be instantly revoked server-side; no token expiry edge cases; well-understood pattern
- **Cons**: Requires Redis to store session state — adds a stateful dependency to the auth flow; sessions don't work well with multi-replica AKS deployments unless Redis is used for shared session storage (which we already have, but coupling auth to Redis creates a critical dependency); JWT is stateless and works across all pod replicas without coordination
- **Why not**: JWT statelesness is a better fit for AKS horizontal scaling. The trade-off (cannot instantly revoke a token without a blocklist) is acceptable given the 8-hour expiry and the internal-only user base.

## Consequences

### Positive
- Zero external dependencies in development — `docker-compose up` gives a fully functional auth system
- FastAPI's `Depends()` system makes role enforcement declarative and testable (`require_role("admin")` reads cleanly)
- JWT payload contains the role, so authorisation checks are O(1) without a database lookup per request
- Adding a new role requires only a new string in the `require_role()` call — no schema changes

### Negative
- **No instant token revocation**: A stolen JWT is valid until it expires (8 hours). Mitigation: use short expiry (8h is already short for an internal tool) and implement a token blocklist in Redis if needed in future.
- **Password storage responsibility**: We store hashed passwords in Cosmos MongoDB. bcrypt is the correct choice (work factor configurable), but this means we are responsible for password security that Azure AD would handle for us.
- **No MFA**: JWT + password auth has no second factor. Acceptable for an internal document management tool; unacceptable for patient-facing systems.

### Risks
- **JWT_SECRET misconfiguration**: If `JWT_SECRET` is weak or shared across environments, tokens from dev can be used in prod. Mitigation: `JWT_SECRET` has **no default** — `pydantic-settings` raises `ValidationError` at startup if the variable is absent, so the application cannot boot with a missing or placeholder secret. It is generated per-environment by Terraform and stored in Key Vault.
