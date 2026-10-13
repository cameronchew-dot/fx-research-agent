# FX Research Agent

An isolated, token-efficient research workspace for proposing, predeclaring,
testing, and reviewing FX hypotheses. It is not a trading service.

## Authority boundary

The research agent has no OANDA credentials and no broker code. Market data is
collected by a separate credentialed collector and exported through a sanitized,
immutable manifest. Exports may contain candles, bid/ask snapshots, spreads,
tick-rate and quote-pressure proxies, regime features, and data-quality flags.
They may not contain account, position, balance, order, transaction, token, or
credential fields.

Spot FX has no centralized tape. Any CVD-like field is explicitly labeled as an
OANDA venue quote/tick-pressure proxy, never as true market-wide volume.

## System of record

This repository becomes the canonical home for new research hypotheses. The
seven EUR agent records are imported once as immutable genesis history. The EUR
agent retains its existing rows as a historical downstream mirror.

```bash
python3 ops/research_supervisor.py init-db
python3 ops/research_supervisor.py import-genesis
python3 ops/research_supervisor.py status
python3 ops/research_supervisor.py backlog
python3 ops/research_supervisor.py sync-market-exports
python3 ops/research_supervisor.py market-data-status
```

No command in this repository can place a trade or change another repository's
lifecycle state.

The normal forward data path is incremental: `eur_bot` writes compressed,
market-only packages under `exports/fx_research`, and this repository validates,
copies, and registers them. The importer rejects checksum mismatches, immutable
ID conflicts, stale/gapped packages for testing, and any broker-account field.
The installed one-shot launch agents run both sides every 15 minutes and write
local operational status to `data/eur_research_market_export.json` in the bot
and `data/market_ingest_status.json` plus `data/market_data_status.json` here.

