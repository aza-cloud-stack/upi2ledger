# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in upi2ledger, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email: **[TODO: add security contact email]**

You should receive a response within 72 hours. We will work with you to understand
the issue and coordinate a fix before any public disclosure.

## What Qualifies

- Authentication bypass
- SQL injection
- Secret/credential exposure
- Cross-site scripting (XSS)
- Path traversal
- Any issue that could expose financial data

## Scope

This policy applies to the upi2ledger codebase. It does not cover:
- Your self-hosted deployment configuration
- Third-party dependencies (report those upstream, but do let us know)
- Google Gmail API or OAuth2 infrastructure

## Security Design

- All user input validated via Pydantic models
- SQL queries are parameterized (no string interpolation)
- Jinja2 autoescaping enabled
- OAuth2 tokens stored with restricted file permissions
- No financial data in logs
- HTTP security headers enforced
- Dependencies audited via pip-audit in CI
- Pre-commit hooks scan for accidental secret commits
