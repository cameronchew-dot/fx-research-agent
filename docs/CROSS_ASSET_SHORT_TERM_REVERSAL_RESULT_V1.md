# Cross-Asset Short-Term Reversal V1 Result

## Decision

`HISTORICAL_GATE_FAIL`

The frozen cross-asset overshoot rule is a credible near-miss, not a validated
strategy. It must not be added to the Alpaca paper executor and must not be
rescued by changing its z-score threshold, holding period, universe, or costs
after seeing this result.

The immutable Alpaca SIP export contained 21,824 adjusted daily bars: exactly
2,728 common sessions for each of `SPY`, `EFA`, `IEF`, `TLT`, `GLD`, `DBC`,
`UUP`, and `BIL`. The rule generated 378 non-overlapping events, approximately
0.68 per week.

## Primary cost result

The primary model charged 5 basis points each way.

| Partition | Events | Net/event | Excess BIL/event | Positive | Compounded | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, 2016-2021 | 207 | +0.1215% | +0.1121% | 56.0% | +25.3% | -18.8% |
| Validation, 2022-2024 | 111 | +0.2521% | +0.2251% | 47.7% | +30.5% | -7.7% |
| Dated, 2025-2026 | 60 | +0.1619% | +0.1272% | 58.3% | +9.0% | -10.9% |

Across validation plus dated confirmation, average net return was `+0.2205%`
and average excess-BIL return was `+0.1907%` over 171 events. It beat the
recent-winner, deterministic-random, and SPY controls on average. However:

- excess-BIL t-statistic was `1.471`, below the locked `1.96` gate;
- paired t-statistics were `1.918` versus the winner, `1.796` versus random,
  and `1.146` versus SPY, all below `1.96`;
- positive-event rate was `51.46%`, below the locked `52%` gate.

At the stress cost of 10 basis points per side, average excess-BIL return
remained positive in all three partitions but statistical evidence weakened.
Development net return fell to `+0.0215%` per event and its maximum drawdown
reached `-28.0%`.

## Consequence

This result is informative evidence that cross-asset overshoots may contain a
small reversal effect, but the predeclared proof standard was not met and the
observed frequency is below the desired one trade per day. The campaign is
closed without paper, promo, or execution authority. Any successor must be a
new economically motivated hypothesis using genuinely new evidence, not a
threshold or holding-period sweep over these used partitions.
