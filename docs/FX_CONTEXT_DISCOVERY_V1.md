# FX Context Discovery V1

## Purpose

`EUR_USD_CONTEXT_DISCOVERY_V1` is an outcome-blind search for recurring
cross-market states around completed EUR/USD M15 decisions. It follows the
closed raw-price motif experiment but tests a genuinely different information
axis: EUR-cross confirmation, broad-dollar context, risk regime, and bond-price
shock proxies.

It is research-only. Coverage readiness is not evidence of edge and cannot
create a campaign, export a finding, or affect paper/live execution.

## Frozen development inputs

The development interval is `2018-09-20T00:00:00Z` through, but excluding,
`2023-01-01T00:00:00Z`.

| Source | Role | Granularity | Development rows | Distinct days | Status |
|---|---|---:|---:|---:|---|
| EUR/USD | primary price | M15 | 106,469 | 1,336 | PASS |
| EUR/GBP | EUR confirmation | M15 | 106,469 | 1,336 | PASS |
| EUR/JPY | EUR confirmation | M15 | 106,440 | 1,336 | PASS |
| XAU/USD | broad-dollar proxy | M15 | 101,130 | 1,330 | PASS |
| SPX500/USD | risk regime | H1 | 25,242 | 1,331 | PASS |
| NAS100/USD | risk regime | H1 | 25,241 | 1,331 | PASS |
| USB10Y/USD | US yield-shock proxy | H1 | 25,229 | 1,331 | PASS |
| DE10YB/EUR | German yield-shock proxy | H1 | 21,720 | 1,089 | PASS |

Every non-primary feature must be joined using a candle whose end time is no
later than the EUR/USD M15 decision time. The bond instruments are CFD price
proxies, not literal yield observations; their returns therefore represent
bond-price shocks and must be signed/interpreted accordingly.

## Coverage audit

- Audit ID: `FX_CONTEXT_COVERAGE_6fb932866587851adc98`
- Contract SHA-256: `c6d02252a5fcacc6ba5d9aac12069da8e881292957f24c62f5eb9e327fb583f6`
- Result: `READY_FOR_OUTCOME_BLIND_CONTEXT_DISCOVERY`
- Blocked sources: none
- Future outcomes read: no
- Strategy labels read: no
- Validation or holdout outcomes read: no

## Deliberate exclusions

- Markov and HMM artifacts are current snapshots, not complete point-in-time
  historical state series. The HMM was fit with later data.
- Walk-forward GARCH forecasts begin in 2022 and do not cover the full frozen
  development interval.
- Current FRED/COT artifacts do not provide a complete release-lagged historical
  export suitable for point-in-time joins.
- Options skew and economic-surprise histories are not available as complete,
  licensed or official point-in-time datasets.

These inputs may enter a later version only through a new contract and a fresh
hypothesis budget. They cannot be added to V1 after outcomes are inspected.

## Next gate

Build the fixed outcome-blind context matrix from the committed feature list,
fit the declared 20-cluster deterministic model on development only, and review
descriptive clusters before predeclaring any direction, horizon, geometry, or
outcome test. Validation (`2023-2024`) and the `2025+` holdout remain sealed.
