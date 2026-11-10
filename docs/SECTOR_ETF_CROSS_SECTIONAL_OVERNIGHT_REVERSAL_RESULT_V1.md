# Sector ETF Cross-Sectional Overnight Reversal V1 Result

## Decision

`HISTORICAL_GATE_FAIL`

The frozen rule achieved the requested opportunity cadence but did not produce
edge. It selected one negative-overnight sector ETF on about 4.0 to 4.6 sessions
per week, then bought at the 09:45 New York bar open and exited at the 10:15
bar close. Both untouched partitions lost money before and after realistic
costs. The campaign must not enter Alpaca shadow execution, paper execution, or
an LLM selector.

The immutable Alpaca SIP panel contained 2,705 common complete sessions from
2016-01-05 through 2026-11-06. The primary population contained 2,282 events
across development, chronological validation, and dated confirmation.

## Primary cost result

The primary model charged 2 basis points each way.

| Partition | Events | Events/week | Gross/event | Net/event | Positive | Sharpe | Positive months | Compounded | Max drawdown | NW t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, 2016-2021 | 1,205 | 4.02 | +0.0422% | +0.0022% | 46.80% | +0.05 | 37.50% | +0.30% | -27.02% | +0.11 |
| Validation, 2022-2024 | 652 | 4.36 | +0.0077% | -0.0323% | 50.31% | -0.86 | 36.11% | -19.82% | -20.92% | -1.56 |
| Dated, 2025-2026 | 425 | 4.61 | -0.0157% | -0.0557% | 43.06% | -1.40 | 30.43% | -21.69% | -23.76% | -2.20 |

Across validation plus dated confirmation, the rule generated 1,077 events at
4.46 per week. Gross return was `-0.0015%` per event before costs and net return
was `-0.0415%` per event. The positive-event rate was `47.45%`, annualized
Sharpe was `-1.08`, positive-month rate was `33.90%`, maximum drawdown was
`-39.71%`, and the Newey-West t-statistic was `-2.59`.

At 5 basis points per side, validation-plus-dated average net return fell to
`-0.1015%` per event, Sharpe fell to `-2.63`, and maximum drawdown reached
`-67.46%`. The primary rule failed every performance, consistency, risk,
significance, and paired-control gate at both cost assumptions. Only the three
minimum-sample gates passed.

## Frequency consequence

This result separates cadence from edge. A deterministic emitter can produce
roughly the desired three-to-five weekly opportunities, but this particular
population would lose money if treated as trades. The frequency target remains
a portfolio design objective, not a reason to lower evidence or cost gates.

## LLM consequence

The LLM forward-shadow flag is false. Context, memory, and calibrated
probabilities cannot be evaluated honestly as a post-result rescue layer on a
historically negative base population. Any future LLM selection experiment
must begin with a separately predeclared forward population and preserve
past-only memory, arm blindness, and no execution authority.

## Consequence

Close the current overnight-reversal family. Do not sweep sector subsets,
overnight-gap thresholds, dispersion thresholds, entries, exits, or holding
windows on these used partitions. No paper, promo, LLM-selection, or order
authority is created by this campaign.
