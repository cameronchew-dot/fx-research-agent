# Cross-Asset ETF Delayed Trend V2 Result

## Current decision

`INDEPENDENT_SOURCE_REPLICATION_PASS_FORWARD_ACCUMULATION`

Twelve Data independently reproduced the V1 delayed-target observation over
the exact same 45 monthly entry intervals from February 2023 through October
2026. This rules out a material Yahoo-specific adjusted-price artifact within
the locked tolerances. It does not turn reused history into fresh confirmation.

## Independent-source comparison

| Cost | Source | Avg monthly excess cash | Sharpe | Information ratio | Max drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| 10 bp | Yahoo V1 reference | +0.3300% | 1.869 | 0.891 | -2.900% |
| 10 bp | Twelve Data V2 | +0.3298% | 1.865 | 0.890 | -2.901% |
| 25 bp | Yahoo V1 reference | +0.2989% | 1.794 | 0.810 | -2.911% |
| 25 bp | Twelve Data V2 | +0.2987% | 1.789 | 0.809 | -2.912% |

All cross-source replication gates passed at both costs. The independent panel
contains 4,743 complete common trading days from `2008-01-02` through
`2026-11-06`; its sealed SHA-256 is
`86a7528a62ec231e32b5477a6a594355b0acd309197f55369609bee8d076055c`.

## Forward status

- Forward start: `2026-12-01`
- Resolved independent monthly intervals: `0/36`
- Review status: `FORWARD_ACCUMULATION`
- Promotion or execution authority: none

The first forward outcome cannot resolve until the first delayed monthly
holding interval has completed. Historical results remain selection and
measurement-replication evidence only.
