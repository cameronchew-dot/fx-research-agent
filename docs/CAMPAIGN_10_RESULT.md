# Campaign 10 Result

## Decision

`HYP_USDJPY_MOF_INTERVENTION_EPISODE_V1` is **rejected under its locked
specification**. No observable-proxy campaign, strategy profile, lifecycle
draft, or trading authority follows from this audit.

The audit used official Ministry of Finance intervention dates only as delayed,
retrospective labels. They were never treated as information available to a
trading system at event time.

## Locked audit

- 361 official daily intervention records formed 72 independent, completely
  priced episodes.
- Episodes were separated by five consecutive BIS trading days without a
  same-direction intervention, or immediately by a direction change.
- Entry was the BIS USD/JPY daily average on the last trading day before the
  first intervention; exit was five trading days after the episode ended.
- Policy direction was long USD/JPY for USD-buying intervention and short
  USD/JPY for USD-selling intervention.
- The primary audit charged 5 basis points round trip; stress charged 10 basis
  points.
- Controls were opposite direction and intervention-free windows shifted by
  60 and 120 BIS trading days.

## Results

| Partition | N | Average net return, 5 bp | Positive rate |
| --- | ---: | ---: | ---: |
| Development | 43 | +0.1654% | 62.8% |
| Chronological OOS | 14 | +0.6117% | 57.1% |
| Dated confirmation | 15 | +0.2731% | 53.3% |

At the 10 bp stress cost, average net returns remained positive: +0.1154% in
development, +0.5617% in OOS, and +0.2231% in dated confirmation.

The dated confirmation beat the opposite-direction control by 0.6461
percentage points and the +120-day control by 0.1281 points. It **lost** to the
+60-day control by 0.3270 points. The +60-day control also had only 9 usable
dated episodes, below the locked minimum of 10.

## Interpretation

The policy-aligned behavior is suggestive, but it does not distinguish itself
from the predeclared nearby-time control. The positive partition results are
therefore insufficient evidence that intervention episodes provide a unique,
replicable mechanism suitable for observable-proxy research.

The horizon, clustering rule, controls, and thresholds will not be adjusted
after seeing this result. Any future intervention-related campaign requires a
new independent economic hypothesis, new predeclaration, and unused evidence.

## Data-quality note

The first local evaluation exposed non-finite observations in the raw BIS
archive. That run was invalid and discarded before interpretation. The
extractor now excludes non-finite source observations, the evaluator rejects
non-finite or non-positive normalized prices, and a regression test enforces
that contract. The results above come only from the corrected finite panel.

Machine-readable results are stored in:

- `data/results/usdjpy_mof_intervention_primary.json`
- `data/results/usdjpy_mof_intervention_stress.json`
