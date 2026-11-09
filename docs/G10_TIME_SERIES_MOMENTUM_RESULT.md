# G10 Daily Time-Series Momentum Diagnostic Result

`CAMPAIGN_G10_DAILY_TIME_SERIES_MOMENTUM_SPOT_DIAGNOSTIC_V1` was evaluated
once under its locked 21/63/126-common-day majority specification. It is
rejected and must not be retuned or promoted.

| Window | Weeks | Avg weekly net, 5 bp | Annualized log return | Sharpe | Positive years | Max log drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development | 1,620 | +0.0391% | +2.03% | 0.48 | 78.1% | -13.6% |
| Chronological OOS | 540 | +0.0267% | +1.39% | 0.26 | 54.5% | -6.3% |
| Dated confirmation | 540 | -0.0468% | -2.44% | -0.77 | 18.2% | -27.1% |

The final partition covers roughly eleven years. At the locked 10 bp turnover
stress, dated confirmation deteriorated to `-3.49%` annualized log return,
`-1.11` Sharpe, and `-38.0%` maximum log drawdown.

The 5 bp dated result beat only the one-week-stale control. It trailed the
opposite-direction control, the fixed-hash random-direction control, and the
single-USD-factor trend baseline. The failure is therefore not explained by
the missing financing leg: the spot-only primary itself failed absolute,
stability, drawdown, and control-edge gates.

This result closes only the exact seven-pair weekly ensemble. It does not test
cross-asset trend following, the separate monthly G10 cross-sectional MOM(1,1)
campaign, or a differently predeclared economic mechanism. No validation
threshold, lookback, universe member, or portfolio constraint will be changed
after seeing this holdout.
