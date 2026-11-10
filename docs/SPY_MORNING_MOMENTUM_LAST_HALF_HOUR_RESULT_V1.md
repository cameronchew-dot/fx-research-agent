# SPY Morning Momentum Last-Half-Hour V1 Result

## Decision

`HISTORICAL_GATE_FAIL`

The practical long-or-cash version of the published intraday-momentum lead does
not have cost-clean edge. It must not be added to the Alpaca paper executor.

The immutable Alpaca SIP export contained 2,180,045 minute bars. The evaluator
retained 2,713 complete regular sessions and observed 1,514 primary trades.
Every predeclared sample-count gate passed.

## Primary cost result

The primary model charged 2 basis points each way.

| Partition | Trades | Net/trade | Sharpe | Positive months | Compounded return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development, 2016-2021 | 833 | -0.0427% | -2.02 | 12.5% | -30.12% |
| Validation, 2022-2024 | 421 | -0.0469% | -2.63 | 13.9% | -18.00% |
| Dated, 2025-2026 | 260 | -0.0267% | -1.94 | 34.8% | -6.75% |

The dated period's gross return averaged approximately `+0.0133%` per trade,
but that was far below the locked `0.04%` round-trip cost. The development and
validation gross averages were already negative before costs.

Across validation plus dated confirmation, the primary rule was less negative
than always trading and the prior-day lag control, but slightly worse than the
opposite-morning-sign control. Its paired Newey-West t-statistic versus the
opposite control was `-0.057`, providing no evidence that the morning sign
selected the better direction. Stress costs worsened every result.

## Consequence

Do not move the exit toward 16:00, add a morning threshold, or condition on
volume after seeing this result. Those would be new hypotheses, not repairs.
This campaign is closed without paper, promo, or execution authority.

The next short-horizon research should move to a less execution-sensitive
one-to-five-day cross-asset mechanism rather than another SPY minute-level
timing variant.
