# QQQ Overnight-Gap First-Half-Hour Reversal V1 Result

## Decision

`HISTORICAL_GATE_FAIL`

The frozen QQQ negative-gap reversal produced the intended frequency but did
not produce durable or cost-clean edge. It must not be added to the Alpaca
paper executor or used as a base population for an LLM selector.

The immutable Alpaca SIP export contained 2,106,563 adjusted minute bars. The
evaluator retained 2,720 complete sessions and 1,164 negative-gap trades across
the three sealed partitions, approximately 2.1 to 2.4 trades per week.

## Primary cost result

The primary model charged 2 basis points each way.

| Partition | Trades | Trades/week | Gross/trade | Net/trade | Positive | Sharpe | Compounded | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, 2016-2021 | 612 | 2.03 | +0.0433% | +0.0033% | 50.5% | +0.07 | +1.4% | -7.8% |
| Validation, 2022-2024 | 357 | 2.37 | -0.0123% | -0.0523% | 45.4% | -1.13 | -17.4% | -18.1% |
| Dated, 2025-2026 | 195 | 2.10 | -0.0002% | -0.0402% | 48.2% | -0.86 | -7.7% | -9.5% |

Across validation plus dated confirmation, the rule generated 552 trades at
2.27 per week. Average net return was `-0.0481%` per trade, the positive-trade
rate was `46.38%`, annualized Sharpe was `-1.04`, and maximum drawdown was
`-24.43%`. The primary signal was less negative than always buying the opening
window, but it was worse than buying after a non-negative gap and failed the
lagged-signal comparison. Only the paired statistic versus always-long exceeded
1.96; the opposite-gap and lagged comparisons did not.

At 5 basis points per side, validation-plus-dated average net return fell to
`-0.1081%` per trade and maximum drawdown reached `-45.35%`. No performance,
risk, consistency, or paired-control case supports activation.

## LLM and probability consequence

Context, memory, and calibrated probabilities remain potentially useful when
the deterministic emitter defines a population with at least plausible base
expectancy. Here, both untouched validation partitions are negative before
primary costs or approximately flat before costs. Asking an LLM to rescue this
population would create a high-dimensional post-result filtering exercise, not
an honest extension of the FX-agent experiment. The result therefore sets
`llm_selector_eligible` to false.

Any future equity LLM experiment must start from a separately predeclared event
population, use forward-only outcomes, maintain arm blindness and past-only
memory, and calibrate probabilities without changing execution gates
automatically.

## Provenance note

The locked campaign was committed and pushed as Git commit `fe97772` at
`2026-11-10T15:03:45Z`, before the QQQ export completed at
`2026-11-10T15:10:07Z`. The immutable campaign JSON contains a manually entered
`created_at_utc` of `15:15:00Z`; that field is a wall-clock metadata error and
is left unchanged to avoid rewriting the predeclared payload. Git history is
the authoritative predeclaration timestamp.

## Consequence

Close this campaign without paper, promo, LLM-selection, or execution
authority. Do not rescue it with gap-size, volatility, weekday, entry, exit, or
holding-window filters on these used partitions.
