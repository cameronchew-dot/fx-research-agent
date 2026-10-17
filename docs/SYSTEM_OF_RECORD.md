# Research System Of Record

## Canonical ownership

`fx_research_agent` owns all new hypothesis intake, state transitions,
predeclared experiment specifications, experiment runs, controls, findings, and
downstream research exports.

The EUR trading agent's seven existing records are immutable genesis history.
They remain readable in the EUR agent database, but new proposals and state
changes belong here. No process writes directly across repositories.

## Data flow

```text
OANDA market-data credential
        |
        v
credentialed collector (outside this repository)
        |
        v
sanitized immutable market export + manifest + checksum
        |
        v
fx_research_agent (read-only market research)
        |
        v
human-reviewed sealed research pack
        |
        v
downstream bot/agent import and independent lifecycle gates
```

The collector may export completed candles, bid/ask snapshots, spreads,
tick-rate, quote-pressure/tick-imbalance proxies, regime features, macro
context, and data-quality flags. It must not export broker-account or trading
state.

Forward packages are cursor-based deltas. The first operational package seeds a
recent window; complete historical backfills are separate, predeclared research
campaigns so scheduled ingestion does not duplicate large datasets or silently
change an experiment's sample.

Multi-instrument literature replications use a stricter completeness boundary:
every declared instrument must supply every required data class over the common
testing window. A partial panel remains `BLOCKED_DATA_READINESS`; the runner may
not substitute spot returns for excess returns, infer missing financing, or
silently shrink the currency universe after results are visible.

## Tape and CVD language

EUR/USD is decentralized. OANDA provides one venue's prices and liquidity
observations, not a consolidated tape. Tick direction, quote pressure, and
liquidity changes may be useful contextual proxies, but they must be labeled as
OANDA-specific and may not be described as true market-wide CVD.

## Authority

Research automation may eventually propose hypotheses, prepare locked
specifications, execute approved offline tests, and write findings. It may not
activate a strategy, change lifecycle state downstream, place an order, or
rewrite an existing immutable record.

