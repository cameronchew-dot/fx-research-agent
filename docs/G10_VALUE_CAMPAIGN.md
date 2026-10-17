# G10 Real Exchange-Rate Value Campaign

Campaign 6 is one predeclared replication, not a parameter search. It uses the
negative five-year change in each currency's real bilateral exchange rate
against USD, following the benchmark value definition described in ECB Working
Paper 2731.

## Locked Inputs

- Monthly end-of-period spot: BIS `WS_XRU`, normalized as USD per unit of
  foreign currency.
- CPI: OECD `DF_PRICES_ALL`, national all-items CPI index, not seasonally
  adjusted. Australia and New Zealand's long-history quarterly CPI series are
  joined as-of without interpolation.
- Every CPI observation receives a fixed two-month information lag. Current
  official vintages are used, so historical revisions remain a documented
  limitation.

## Locked Test

At each common month-end, compute the real exchange rate and its 60-month
change. Buy the three most depreciated currencies and sell the three most
appreciated currencies, equally weighted within each leg, for one month.
Primary costs are 5 bps per unit of portfolio turnover; the only stress run is
10 bps. Controls are opposite ranks, one-month-stale ranks, and a fixed-hash
cross-sectional permutation.

The outcome is next-month spot return, not currency excess return. Therefore a
survivor would establish spot-predictive evidence only; it cannot be treated as
a carry-inclusive trading result.

No parameter changes, universe changes, or alternative value definitions are
allowed after results are inspected. The campaign has no order authority and
cannot activate any downstream bot or agent.
