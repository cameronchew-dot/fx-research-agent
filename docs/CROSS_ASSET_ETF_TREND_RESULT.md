# Cross-Asset ETF Trend V1 Result

## Decision

`REJECTED_AS_SPECIFIED_CONTROL_NOT_DEFEATED`

The locked primary was positive after costs in development, chronological OOS,
and dated confirmation. It also remained positive under the predeclared 25 bp
one-way stress. The exact campaign nevertheless fails because the one-month-
stale control outperformed the primary in dated confirmation. The evidence
supports continued research into the broader cross-asset trend mechanism, but
does not validate the selected monthly target-refresh timing.

## Primary results

| Partition | Months | Avg monthly excess cash | Annualized log return | Sharpe | Information ratio | Positive years | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Development | 132 | +0.169% | +2.387% | 0.421 | 0.357 | 75% | -8.352% |
| Chronological OOS | 44 | +0.160% | +2.756% | 0.542 | 0.374 | 60% | -4.956% |
| Dated confirmation | 45 | +0.227% | +7.083% | 1.574 | 0.610 | 100% | -3.069% |

At 25 bp one-way cost, chronological OOS averaged `+0.139%` excess cash per
month and dated confirmation averaged `+0.195%`; dated Sharpe was `1.492`,
information ratio was `0.524`, and maximum drawdown was `-3.081%`.

## Dated controls at 10 bp

| Portfolio | Avg monthly excess cash | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: |
| Locked primary | +0.227% | 1.574 | -3.069% |
| Vol-balanced buy-and-hold | +0.216% | 1.452 | -3.393% |
| Opposite trend | +0.024% | 1.049 | -3.812% |
| Fixed-hash random activation | -0.107% | 0.559 | -5.527% |
| One-month-stale target | +0.330% | 1.869 | -2.900% |

The stale control also remained stronger at 25 bp. Selecting it now as the
winner would be post-selection, so it is preserved only as a new confirmatory
lead. `HYP_CROSS_ASSET_ETF_DELAYED_TREND_CONFIRMATION_V2` must use an
independent adjusted-price source and evidence not used to select the delay.
It cannot inherit V1 evidence or authority.

## Boundaries

- Yahoo adjusted closes were discovery-only.
- No result can activate a downstream strategy or place an order.
- V1 is closed and must not be retuned on its used partitions.
- V2 remains proposed until its independent data and fresh confirmation
  contract are frozen.
