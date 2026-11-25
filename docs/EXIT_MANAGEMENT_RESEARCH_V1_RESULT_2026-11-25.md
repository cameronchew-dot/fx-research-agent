# Exit Management Research V1 Result

Generated from immutable EUR/USD evidence on 2026-11-25. This is historical,
post-hoc research with no campaign, policy, order, paper, or live authority.

## Frozen comparison

Every policy used the same next-M15-open entry, observed decision spread,
initial `-1R` stop, and 16-bar horizon. The control exited at `+1.5R`. The
alternatives were:

- move the full-position stop to break-even after a `+1R` touch;
- take 50% at `+1R` and target `+2R` on the remainder with the original stop;
- take 50% at `+1R`, then move the runner stop to break-even and target `+2R`.

Management became active on the candle after the `+1R` touch. Ambiguous
same-candle paths used stop-first ordering. Partial exits paid an additional
fill-cost proxy. All six alternative comparisons shared one
Benjamini-Hochberg false-discovery family.

## Results

| Population and policy | N | Avg net R | Positive rate | Lift vs control | FDR q |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original control | 257 | -0.209 | 32.3% | - | - |
| Original break-even after 1R | 257 | -0.193 | 28.4% | +0.016 | 0.297 |
| Original 50% at 1R, 2R runner | 257 | -0.234 | 31.1% | -0.026 | 0.000032 |
| Original 50% at 1R, BE 2R runner | 257 | -0.212 | 38.9% | -0.003 | 0.000032 |
| Strategy-shadow control | 334 | -0.043 | 39.8% | - | - |
| Strategy-shadow break-even after 1R | 334 | -0.074 | 32.9% | -0.031 | 1.000 |
| Strategy-shadow 50% at 1R, 2R runner | 334 | -0.085 | 37.7% | -0.042 | <0.000001 |
| Strategy-shadow 50% at 1R, BE 2R runner | 334 | -0.092 | 46.4% | -0.049 | <0.000001 |

Replay validation covered 257 of 269 eligible original events and 334 of 343
eligible strategy-shadow events. The remaining 21 rows failed the strict
control-reproduction tolerance and were excluded rather than approximated.

## Decision

No tested exit-management alternative improves the evidence base. The small
`+0.016R` original-population lift from break-even is not significant and both
chronological halves remain negative in absolute expectancy. Every partial-
profit policy lowers average R. The partial-plus-break-even policy increases
the percentage of positive outcomes, but does so by cutting average expectancy;
that is a smoother-looking result, not better edge.

Do not create a campaign or change execution from this result. Continue using
the frozen control for comparable research outcomes. Revisit exit management
only for a separately predeclared mechanism with its own causal reason, not by
resweeping these same outcomes.

