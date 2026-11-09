# Cross-Asset ETF Trend V1

This campaign is the first deliberate move beyond narrow spot-FX signal
discovery. It tests one fixed, small-account-feasible portfolio across US and
international equities (`SPY`, `EFA`), intermediate and long Treasuries (`IEF`,
`TLT`), gold and broad commodities (`GLD`, `DBC`), and the US dollar (`UUP`).
`BIL` represents unallocated cash.

At each completed month end, an asset is held during the next monthly interval
only when its prior 252-common-day adjusted total return is positive. Active
assets receive inverse-63-day-volatility weights, capped at 25% per asset and
40% per equity, bond, or real-asset class; currency exposure is capped at 20%.
The remainder stays in `BIL`. Primary costs are 10 bp per unit of one-way risky
asset turnover, with a locked 25 bp stress.

The four controls are opposite-trend long-only, one-month-stale targets,
fixed-hash random activation, and volatility-balanced buy-and-hold. The final
20% of monthly observations is dated confirmation and may be opened only after
this specification is frozen.

## Data boundary

Yahoo chart adjusted closes make the initial run reproducible without a paid
feed, but they are a discovery source. A surviving result remains ineligible
for downstream use until the exact observations and conclusions are confirmed
against an independent distributions-adjusted source. This repository retains
no account credentials and grants no order authority.

## Reproduction

```bash
python3 ops/cross_asset_etf_adjusted_extract.py \
  --output data/external/cross_asset/adjusted_daily.csv.gz \
  --summary data/external/cross_asset/adjusted_daily.summary.json

python3 ops/cross_asset_etf_trend_research.py \
  --output data/results/cross_asset_etf_trend_primary.json

python3 ops/cross_asset_etf_trend_research.py --cost-bps 25 \
  --output data/results/cross_asset_etf_trend_stress.json
```

## Completed result

The primary remained positive in development, chronological OOS, dated
confirmation, and the 25 bp cost stress. It did not pass the full contract:
the one-month-stale control produced stronger dated excess return and
risk-adjusted performance. V1 is therefore closed as
`REJECTED_AS_SPECIFIED_CONTROL_NOT_DEFEATED`, with no retuning and no downstream
authority. See `docs/CROSS_ASSET_ETF_TREND_RESULT.md`.

The delayed target is retained only as a post-control confirmatory lead. It
requires an independent adjusted-price source and fresh evidence; the used V1
dated window cannot confirm it.
