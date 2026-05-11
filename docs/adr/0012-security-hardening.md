# ADR-0012: Security Hardening — Rate Limiting, Auth Scope, and Upload Validation

**Date**: 2026-05-11
**Status**: accepted
**Deciders**: KB RAG system design

## Context

A security review of the v1 backend identified several exploitable gaps:
unauthenticated task and search endpoints allowed any internet user to burn Azure
OpenAI credits; the login endpoint had no brute-force protection; the upload handler
trusted the client-supplied Content-Type header and had no file size cap; the JWT
algorithm was configurable at runtime (enabling algorithm confusion attacks); and
the API served Swagger UI publicly in production. These were addressed as a single
hardening sprint rather than piecemeal to establish a coherent security baseline
before production deployment.

## Decision

We apply five security controls in one release:

1. **Rate limiting via `slowapi`**: 10 req/min on `/manage/auth/token` (brute-force
   protection), 30 req/min on `/qa/ask` (LLM cost protection), IP-based
2. **Auth scope expanded**: All `/tasks/*` and `/search/*` endpoints now require a
   valid JWT; previously these were fully unauthenticated
3. **JWT hardening**: Algorithm hardcoded to `HS256` in `auth.py` (not configurable);
   expiry reduced from 480 to 60 minutes
4. **Upload validation at API layer**: 50 MB size cap + magic-bytes check before
   writing to ADLS; content-type header alone is no longer trusted
5. **Security headers + production lockdown**: `SecurityHeadersMiddleware` adds
   HSTS/X-Frame-Options/X-Content-Type-Options; `/docs`, `/redoc`, `/openapi.json`
   disabled when `DEBUG=false`

## Alternatives Considered

### Alternative 1: Rate limit at Azure API Management (APIM) layer only
- **Pros**: Centralised; no application-level code; easier to update limits
- **Cons**: APIM is only in the AKS ingress path — direct pod access (e.g., during
  development, or if APIM is bypassed) would have no protection
- **Why not**: Defence in depth requires the application to protect itself regardless
  of whether a gateway is in front of it

### Alternative 2: Azure AD / managed identity for task/search auth
- **Pros**: Token revocation, short-lived credentials, no JWT secret management
- **Cons**: Significantly increases complexity for the CMS developer workflow;
  requires service principal setup for every consumer
- **Why not**: Out of scope for v1; the JWT RBAC already in place (ADR-0006) is
  sufficient for the current single-tenant CMS use case

### Alternative 3: Configurable rate limit values in env vars
- **Pros**: Tunable per environment without code changes
- **Cons**: Adds configuration surface; rate limit values are not operational
  concerns — they encode security policy that should be reviewed before changing
- **Why not**: Embedding limits in code makes them visible in code review and ADRs;
  environment-driven limits can be accidentally set too high by ops without a
  security review

## Consequences

### Positive
- Login endpoint is protected against credential stuffing without external tooling
- LLM API costs are bounded per source IP even if JWT tokens are compromised
- Task and search endpoints can no longer be abused to burn Azure OpenAI credits
  anonymously
- Swagger UI is not publicly browsable in production — reduces information leakage
  about the API surface
- Magic-bytes validation at the API layer means malicious files are rejected before
  entering the data lake, not just at processing time

### Negative
- Legitimate high-volume integrations hitting the 30/min Q&A limit will need to
  request a limit increase or use a different rate limit key strategy (e.g.,
  user-based instead of IP-based for authenticated callers behind a NAT)
- 60-minute JWT expiry means users logged into the CMS must re-authenticate more
  frequently; a refresh-token flow would improve UX but was deferred to v2

### Risks
- **IP-based rate limiting behind a load balancer**: If the application is deployed
  behind a NAT or proxy that forwards a single IP, all users share one rate limit
  bucket. Mitigation: configure Kubernetes ingress (nginx/AGIC) to forward
  `X-Real-IP` or `X-Forwarded-For`; slowapi respects these headers when configured
- **50 MB upload cap**: Some large PPTX files with embedded images may exceed this.
  Mitigation: limit is configurable as `_MAX_UPLOAD_BYTES` constant in the
  management router
