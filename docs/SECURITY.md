# Security notes and production hardening TODOs

## In place in the scaffold
- No secrets committed. `.env` is git-ignored; `.env.example` has obviously local-only values.
- Settings refuse the dev auth provider, insecure session cookies, `CAIRN_LOG_SENSITIVE` and local DB credentials when `CAIRN_ENV=production`.
- Website sign-in: scrypt password hashes (stdlib, per-password salt); unknown emails are
  verified against a dummy hash so timing does not reveal which accounts exist, and failed
  sign-ins return one generic message. Sessions are server-side: the cookie is HttpOnly,
  SameSite=Lax (Secure in production) and only a SHA-256 of its token is stored, so a
  database leak yields no usable sessions. Logout and re-login revoke the old session.
- CSRF: every cookie-authenticated POST must carry the session's `X-CSRF-Token`. Login only
  accepts `application/json` (FastAPI's strict content-type default, covered by a test), which
  a cross-site page cannot send without a CORS preflight; no CORS is enabled.
- The website is served same-origin behind nginx with a strict Content-Security-Policy
  (`'self'` only, no inline script), `frame-ancestors 'none'`, nosniff and Referrer-Policy.
- Sign-ins (successful and failed) and sign-outs are audited; attempted emails are not recorded.
- The tenant comes from `ActorContext`, never from request bodies. Repositories require `tenant_id` on every query.
- Cross-tenant ids return 404, the same as a missing resource (no IDOR existence leaks).
- All SQL goes through the ORM with bound parameters.
- Uploads: size limit, content-type allowlist, magic-byte checks, UTF-8 checks for text,
  SHA-256 checksums, and server-generated object keys.
- Access-sensitive reads, consent revocations and all authorization denials are audited.
- Logs redact message text, payloads, observation fields and credentials by default.
- Health outputs are descriptive only, enforced by SafetyPolicy and the contract tests.

## TODO before production
- [ ] Run with `CAIRN_AUTH_PROVIDER=session` (or add OIDC/JWT validation: issuer, audience, expiry, key rotation) and `CAIRN_SESSION_COOKIE_SECURE=true` behind TLS.
- [ ] Login throttling / account lockout and alerting on repeated failed sign-ins (only audited today).
- [ ] Password reset, account deactivation UI, MFA; purge expired `login_sessions` rows on a schedule.
- [ ] Postgres row-level security as a second tenant-isolation layer; separate DB roles for api, worker and migrate.
- [ ] Encrypt at rest (Postgres, Neo4j, MinIO) and use TLS for every hop (Postgres, Bolt, S3, Temporal mTLS).
- [ ] Secrets from a secret manager (no env-file credentials); rotate MinIO, Neo4j and DB credentials.
- [ ] Stream uploads to object storage instead of buffering in memory; add malware scanning.
- [ ] Rate limiting and request-size limits at the edge; per-tenant quotas for AI calls.
- [ ] Retention automation per retention class; legal-hold workflow; data residency per tenant.
- [ ] Tamper-evident audit log (hash chain or WORM storage); audit log access controls.
- [ ] Production Temporal (namespaces per environment, mTLS, payload codec encryption).
- [ ] Neo4j auth hardening and network isolation; Graphiti telemetry disabled (already the default here).
- [ ] Clinical safety case and human review of all health-pack guidance before any real use.
- [ ] Prompt-injection and red-team evaluation sets for the LLM renderer and extraction; enable NeMo rails.
- [ ] Dependency and container image scanning in CI; signed images; SBOM.
- [ ] Put the API behind a gateway: TLS termination, CORS policy for web clients, WAF.
