# Security (internal)

Last updated: 2025-09-21

Internal repo; community updates are not expected.

## Reporting
- Do not open public GitHub issues for security topics.
- Report internally to the owner/maintainers via our usual channels (chat/email). Include steps to reproduce, impact, and the commit/sha.

## Secrets
- Never commit real secrets. Use .env for local and GitHub Actions secrets/variables for CI.
- If a secret leaks, rotate immediately and remove from history when feasible.

## Hardening
- Keep dependencies pinned and up to date (requirements.txt).
- Use strong WEB_USERNAME/WEB_PASSWORD if enabling the web admin; avoid exposing it publicly.
- Run with least privilege; restrict network access where possible.
