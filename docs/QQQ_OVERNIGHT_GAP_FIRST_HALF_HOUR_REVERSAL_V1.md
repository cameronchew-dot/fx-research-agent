# QQQ Overnight-Gap First-Half-Hour Reversal V1

## Status

`PREDECLARED_RESEARCH_ONLY`

This campaign asks whether negative QQQ overnight returns reverse during the
first half hour strongly enough to survive executable timing and costs. It is a
new instrument and outcome population, not a parameter variation of the failed
SPY last-half-hour momentum or cross-asset five-session reversal campaigns.

## Mechanism

The proposed mechanism is overnight overreaction followed by liquidity and
arbitrage activity after the regular-session open. Iwanaga and Sakemoto (2026)
report that overnight returns negatively predict first-half-hour returns for
U.S. market indices, while also warning that the relationship weakened after
the 2010s. The literature therefore motivates one honest test; it does not
establish an executable QQQ edge.

For each complete QQQ regular session:

1. Compare the 09:30 open with the prior complete session's 15:59 close.
2. Activate only when that overnight return is strictly negative.
3. Enter long at the 09:31 open, after the gap direction is observable.
4. Exit at the 09:59 close.
5. Otherwise remain in cash.

No gap-size threshold is used. The fixed controls are always-long over the same
window, long after a non-negative gap, and a one-session-lagged negative-gap
signal.

## Guardrails

- Historical QQQ SIP minute bars use split-and-dividend adjustment `all`.
- Primary costs are 2 basis points per side; stress costs are 5 per side.
- Development is 2016-2021, validation is 2022-2024, and dated confirmation is
  2025 through November 6, 2026.
- There is one signal sign and one holding window. No magnitude, entry, exit,
  volatility, weekday, or regime sweep is allowed after the result.
- A historical pass remains research-only and requires fresh forward review.
- This repository cannot activate paper or submit an order.

Primary reference: Yasuhiro Iwanaga and Ryuta Sakemoto, "Does overnight return
predict the first half-hour return for U.S. market indices?" (2026), SSRN
5807282, DOI `10.2139/ssrn.5807282`.
