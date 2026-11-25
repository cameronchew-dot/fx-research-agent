# Signal Winner Path and Transition Result

Generated from immutable EUR/USD research evidence on 2026-11-25. Historical
regime labels use only candles completed by each decision timestamp. This is a
descriptive result and has no order or policy authority.

## Populations

| Population | Independent outcomes | Positive | Non-positive |
| --- | ---: | ---: | ---: |
| Original failed-auction candidates | 268 | 91 | 177 |
| Strategy-shadow signals | 559 | 194 | 365 |

The populations remain separate because their outcome sources and selection
processes differ.

## Resolved path findings

For strategy-shadow outcomes, positive observations averaged `1.791R` MFE and
`0.516R` MAE. Non-positive observations averaged `0.353R` MFE and `1.203R` MAE.
Approximately 29.0% of non-positive outcomes reached `0.5R` favorable excursion
and 12.1% reached `1R`; only 0.27% reached `1.5R`. This is diagnostic evidence
that some failed trades first moved favorably, but MFE/MAE alone does not reveal
the ordering of favorable and adverse movement and cannot validate a break-even,
partial-profit, or trailing-stop policy.

The average entry-spread-to-stop proxy was `0.240R` for positive strategy
outcomes and `0.339R` for non-positive outcomes. This supports continued cost
measurement, but existing low-cost context slices did not survive the full
multiple-testing correction.

Original failed-auction winners averaged `1.879R` MFE and `0.466R` MAE. Their
entry cost proxy (`0.196R`) was only slightly below the non-positive population
(`0.206R`), so the stronger cost contrast was specific to the broader strategy-
shadow population.

## Regime-transition findings

All 268 original and 559 strategy-shadow independent outcomes received causal
Markov, HMM, and GARCH transition labels. No static or transition slice survived
the shared Benjamini-Hochberg correction.

The strongest cross-signal descriptive transition was persistent
`ASIA|UP|EXPANDING`, with 18 observations across 12 exact signals and average
within-signal residual performance of `+0.694R`. Other positive descriptive
transitions included `NORMAL->HIGH` GARCH (`n=16`, `+0.376R`) and persistent
`LONDON|UP|EXPANDING` Markov state (`n=11`, `+0.290R`). These are small post-hoc
leads, not discovered edge.

## Decision

No new campaign or trading filter is created from this result. The next valid
step is continued forward collection. A transition deserves a locked campaign
only if it repeats with broader support or appears in an independently defined
mechanism without selecting thresholds from these outcomes.
