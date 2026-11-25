# Signal Winner Path and Transition Result

Generated from immutable EUR/USD research evidence on 2026-11-25. Historical
regime labels use only candles completed by each decision timestamp. This is a
descriptive result and has no order or policy authority.

## Populations

| Population | Independent outcomes | Positive | Non-positive |
| --- | ---: | ---: | ---: |
| Original failed-auction candidates | 269 | 91 | 178 |
| Strategy-shadow signals | 343 | 138 | 205 |

The populations remain separate because their outcome sources and selection
processes differ.

## Resolved path findings

For strategy-shadow outcomes, positive observations averaged `1.809R` MFE and
`0.528R` MAE. Non-positive observations averaged `0.378R` MFE and `1.339R` MAE.
Approximately 30.2% of non-positive outcomes reached `0.5R` favorable excursion
and 13.2% reached `1R`; none reached `1.5R`. This is diagnostic evidence
that some failed trades first moved favorably, but MFE/MAE alone does not reveal
the ordering of favorable and adverse movement and cannot validate a break-even,
partial-profit, or trailing-stop policy.

The average entry-spread-to-stop proxy was `0.250R` for positive strategy
outcomes and `0.254R` for non-positive outcomes. The corrected EUR/USD-only
population therefore does not show the earlier apparent cost separation, and
existing low-cost context slices did not survive the full multiple-testing
correction.

Original failed-auction winners averaged `1.879R` MFE and `0.466R` MAE. Their
entry cost proxy (`0.196R`) was only slightly below the non-positive population
(`0.206R`).

## Regime-transition findings

All 269 original and 343 EUR/USD strategy-shadow independent outcomes received causal
Markov, HMM, and GARCH transition labels. No static or transition slice survived
the shared Benjamini-Hochberg correction.

The strongest cross-signal descriptive transition was persistent
`ASIA|UP|EXPANDING`, with 10 observations across six exact signals and average
within-signal residual performance of `+0.860R`. Other positive descriptive
states included `ASIA|UP|EXPANDING` Markov state (`n=21`, `+0.619R`) and
`NORMAL->HIGH` GARCH (`n=12`, `+0.451R`). These are small post-hoc leads, not
discovered edge.

The corrected counts enforce the report's instrument boundary. Non-EUR/USD
strategy outcomes are no longer labeled with EUR/USD regime context or included
in these summaries.

## Decision

No new campaign or trading filter is created from this result. The next valid
step is continued forward collection. A transition deserves a locked campaign
only if it repeats with broader support or appears in an independently defined
mechanism without selecting thresholds from these outcomes.
