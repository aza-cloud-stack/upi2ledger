# upi2ledger

> **WIP** — This project is under active development.

Self-hosted web app that parses UPI transaction emails from Gmail and records them as [hledger](https://hledger.org/) journal entries.

Built for the Indian personal finance ecosystem. Security-first, privacy-first.

## What It Does

```
Gmail → Fetch UPI emails → Parse (regex + optional local LLM) → Review → Write to .journal
```

- Connects to your Gmail via OAuth2
- Parses transaction emails from Google Pay, PhonePe, Paytm, and bank alerts
- Extracts amount, payee, date, and UPI reference
- Maps merchants to hledger expense accounts (learnable)
- Presents a review UI before committing to your journal
- Optional local LLM (Ollama) for ambiguous emails and smart categorization

## Key Principles

- **Self-hosted only** — your data never leaves your machine
- **No cloud dependencies** — Gmail API is the only external call
- **Security first** — see [SECURITY.md](SECURITY.md)
- **Privacy by design** — raw emails stay in Gmail, only structured data is stored locally
- **Open source** — MIT licensed

## Tech Stack

- Python / FastAPI
- HTMX + Jinja2 (lightweight UI)
- SQLite (local storage)
- Ollama (optional, local LLM)
- hledger (plain-text accounting)

## Quick Start

> Detailed setup instructions coming soon.

```bash
git clone https://github.com/<your-username>/upi2ledger.git
cd upi2ledger
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml  # edit with your settings
python -m app.main
```

## Status

See [plan.md](plan.md) for the full implementation roadmap.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

[MIT](LICENSE)
