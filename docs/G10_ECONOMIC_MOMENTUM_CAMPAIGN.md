# G10-Subset Economic Momentum Campaign

Campaign 7 is one predeclared industrial-production momentum test. It is not a
search across the many fundamental variables and horizons in the source paper.

## Locked Inputs

- Monthly end-of-period spot: BIS `WS_XRU`, normalized as USD per unit of
  foreign currency.
- Industrial production: OECD `DF_INDSERV`, production-volume index for total
  industry (`BTE`), seasonally adjusted, monthly.
- The common 1990 history supports EUR, GBP, JPY, CAD, SEK, and NOK. AUD and
  NZD have no matching OECD series; CHF begins only in October 2010. Those
  exclusions were fixed before outcomes were inspected.
- Every macro observation receives a fixed two-month information lag. The OECD
  download is the current official vintage, so revision history is unavailable.

## Locked Test

At each month-end, rank the six currencies by the log change in the latest
timestamp-valid industrial-production index over 60 months. Buy the top two and
sell the bottom two, equally weighted, for one month. Primary costs are 5 bps
per unit of turnover; the only stress run is 10 bps. Controls are opposite
ranks, one-month-stale ranks, and a fixed-hash cross-sectional permutation.

The outcome is next-month spot return, not currency excess return. A survivor
would be eligible only for human review and a vintage-aware follow-up. It would
not establish a carry-inclusive result, enter a batch automatically, activate a
bot or agent, or gain order authority.

No alternative lookbacks, portfolio widths, macro variables, or universe
changes are allowed after results are inspected.
