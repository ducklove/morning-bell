# AGENTS.md

## Project purpose
This project is a read-only Polymarket morning briefing bot. It summarizes public market data and sends notifications. It must not place trades, manage wallets, or provide investment advice.

## Engineering rules
- Keep the code typed and testable.
- Do not commit secrets.
- Prefer deterministic summaries over LLM calls for MVP.
- Handle missing/changed API fields gracefully.
- Any network code must have timeout and retry behavior.
- Keep notifications short and Korean-first.

## Validation
Before finalizing changes, run:

```bash
ruff check .
pytest -q
polymarket-briefing run --config config.example.yaml --dry-run
```

## Safety
Never add order placement, wallet signing, deposit, withdrawal, or credential handling for Polymarket trading.

