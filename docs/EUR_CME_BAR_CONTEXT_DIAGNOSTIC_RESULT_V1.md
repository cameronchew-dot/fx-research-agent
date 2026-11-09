# EUR/USD CME Bar Context Diagnostic V1 Result

## Result

`DIAGNOSTIC_GATE_FAIL`

The locked diagnostic retained 73 non-overlapping EUR/USD failed-auction
episodes. Complete causal 6E context was available for 69 episodes, leaving 39
one-step-ahead predictions after the fixed 30-episode initialization window.

| Model | AUC | Brier | Log loss | Top-tercile average net R | Bottom-tercile average net R |
| --- | ---: | ---: | ---: | ---: | ---: |
| Spot context only | 0.161 | 0.404 | 1.314 | -1.000R | +0.685R |
| Spot plus current 6E context | 0.219 | 0.422 | 1.498 | -0.808R | +0.532R |
| Spot plus 24-hour-lagged 6E context | 0.375 | 0.380 | 1.335 | -0.338R | +0.413R |

Current 6E context improved AUC by `0.058` relative to spot-only context, but
worsened Brier score by `0.018` and log loss by `0.184`. It also lost to the
24-hour-lagged control on every primary metric. Its highest-ranked tercile had
worse realized net R than its lowest-ranked tercile.

The eight-prediction dated tail contained no positive outcomes, so it could not
provide valid dated AUC confirmation and did not meet the predeclared minimum
of 12 predictions.

## Decision

Do not add this CME feature pack to the EUR/USD trading agent. Do not purchase
a live CME subscription on the strength of this result. The purchased 6E data
remain useful for research, but 15-minute return, close location, volume, range,
and realized-volatility ratios did not demonstrate incremental predictive value
for these episodes.

No feature selection, threshold adjustment, or geometry retuning follows this
result. Any materially different CME hypothesis requires a new predeclared
campaign and fresh confirmation; it cannot be presented as a rescue of V1.

This diagnostic has no trading, paper, agent-context, or signal authority.
