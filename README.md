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
```

No command in this repository can place a trade or change another repository's
lifecycle state.

