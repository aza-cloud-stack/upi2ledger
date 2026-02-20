# Contributing to upi2ledger

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/<your-username>/upi2ledger.git
cd upi2ledger
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install
```

## Code Standards

- Type hints on all functions
- Format and lint with `ruff`
- Type check with `mypy --strict`
- Tests required for new parsers and routes
- No secrets, tokens, or PII in code or tests

## Commit Messages

Use [conventional commits](https://www.conventionalcommits.org/):

```
feat: add PhonePe email parser
fix: handle missing UPI ref in bank alerts
security: add rate limiting to login endpoint
docs: update setup instructions
test: add fixtures for HDFC bank alerts
```

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes with tests
3. Ensure all checks pass: `ruff check .`, `mypy .`, `pytest`
4. Open a PR against `main` with a clear description

## Adding a New Email Parser

1. Create `app/parser/regex/yourparser.py`
2. Add sanitized test fixtures in `tests/fixtures/` (no real email data)
3. Register in the parser registry
4. Add tests in `tests/test_parsers/`

## Security

If you find a security issue, do NOT open a public issue. See [SECURITY.md](SECURITY.md).
