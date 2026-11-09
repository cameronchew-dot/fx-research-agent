# Cross-Asset ETF Delayed Trend V2

V2 is a confirmatory follow-up to the rejected V1 specification. V1's locked
one-month-stale control was stronger than its primary, but that observation is
selection evidence. It is not permission to rename the control as a validated
strategy.

## Independent data

V2 uses Twelve Data's daily `/time_series` endpoint with `adjust=all` for the
same eight ETFs. The local API key is read from `TWELVE_DATA_API_KEY` and is
never written to an artifact. Historical Twelve Data results can establish
whether the V1 finding was robust to a different adjusted-price vendor, but
they cannot provide fresh confirmation because those dates helped select the
delay.

The free Basic allowance is sufficient for one eight-symbol refresh. Create a
free Twelve Data key, add `TWELVE_DATA_API_KEY=...` to the local `.env`, then
run:

```bash
python3 ops/cross_asset_twelve_data_extract.py --end 2026-11-30
python3 ops/cross_asset_delayed_trend_v2.py
python3 ops/cross_asset_delayed_trend_v2.py --cost-bps 25 \
  --output data/results/cross_asset_etf_delayed_trend_v2_stress.json
```

After November 2026, refresh the independent panel after each completed month
and rerun both costs. Only resolved holding intervals entered on or after
`2026-12-01` enter the append-only forward ledger. Repeated runs are
idempotent; a provider revision that changes an already-sealed result raises a
conflict instead of silently rewriting history.

## Review boundary

The campaign remains non-promotable until all of the following are true:

- the independent source reproduces V1 within the frozen tolerances;
- at least 36 forward monthly holding intervals are resolved;
- all locked return, risk, control, and 25 bp stress gates pass;
- a human explicitly reviews the result.

This repository has no order authority, and even a passing review cannot
activate downstream behavior.
