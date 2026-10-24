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

- Audit ID: `FX_CONTEXT_COVERAGE_fcea005de04b8d593761`
- Contract file SHA-256: `dad3596d2d4d8b55acf2a4cbf8a80739c6dea8aec4259acd40e680fd0668668f`
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

The fixed matrix and descriptive cluster run are complete:

- Matrix: `CONTEXT_MATRIX_EUR_USD_CONTEXT_DISCOVERY_V1_66b3c310e0de3f97`
- Matrix rows: 106,426
- Features: 26
- Training rows: 100,000
- Discovery run: `CONTEXT_DISCOVERY_cd51825d06845eb400ba`
- Clusters: 20
- Convergence: yes, after 128 iterations
- Outcome comparisons: zero

Notable outcome-blind states include:

| Cluster | Rows | Development fraction | Descriptive context |
|---|---:|---:|---|
| `d61e57ef03f0` | 299 | 0.28% | acute equity risk-off shock with bond-price strength |
| `428107858e20` | 828 | 0.78% | acute equity risk-on shock with EUR/JPY strength |
| `7f5a341de88d` | 1,160 | 1.09% | broader four-hour equity risk-on state |
| `e24aaebd5b32` | 1,322 | 1.24% | synchronized EUR weakness in EUR/GBP and EUR/JPY |
| `eeeacb996004` | 1,428 | 1.34% | joint US/German bond-price rally with positive proxy spread shock |
| `3731a8b37269` | 1,642 | 1.54% | sharp gold decline, concentrated around overlap |
| `8ab54690c14b` | 1,808 | 1.70% | joint US/German bond-price selloff with negative proxy spread shock |
| `a49161ce537a` | 2,348 | 2.21% | moderate equity risk-off state with bond-price strength |
| `821eadf9f637` | 5,076 | 4.77% | EUR-cross strength during London/NY overlap |

The remaining broad clusters are predominantly session and weekday partitions.
That is a useful caution: frequency alone is not a reason to test them.

The next gate is a blind human review selecting a small, economically coherent
subset before any direction, horizon, entry, stop, target, cost model, control,
or outcome test is declared. Validation (`2023-2024`) and the `2025+` holdout
remain sealed.
