# G10-Subset Recursive Output-Gap Campaign

Campaign 8 is one predeclared business-cycle test based on Cenedese, Payne,
Sarno, and Valente (2020). It is distinct from Campaign 7: Campaign 7 ranked
five-year industrial-production growth, while this campaign ranks short-run
cyclical residuals around an estimated trend.

## Locked Inputs And Filter

- Monthly end-of-period spot: BIS `WS_XRU`, normalized as USD per unit of
  foreign currency.
- Industrial production: OECD `DF_INDSERV`, production-volume index for total
  industry (`BTE`), seasonally adjusted, monthly.
- EUR, GBP, JPY, CAD, SEK, NOK, and the US benchmark share a complete history
  from January 1990. Each observation receives a fixed two-month lag.
- At every decision month, regress log industrial production on an intercept
  and its 24-through-35-month lags, recursively using only observations at or
  before the latest timestamp-valid endpoint. Require at least 60 regression
  observations. The output gap is the endpoint residual.

## Locked Portfolio

Rank the six foreign currencies by their output gap relative to the US output
gap. Buy the top two and sell the bottom two, equally weighted, for one month.
Primary costs are 5 bps per unit of turnover; the only stress run is 10 bps.
Controls are opposite ranks, one-month-stale ranks, and a fixed-hash
cross-sectional permutation.

The current OECD vintage contains historical revisions. Recursive endpoints
prevent future observations entering the filter, but cannot undo revisions to
older observations. A survivor therefore requires separate real-time-vintage
confirmation before any broader interpretation. The campaign has no order or
downstream activation authority.
