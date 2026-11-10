# Sector ETF Cross-Sectional Overnight Reversal V1

## Status

`PREDECLARED_RESEARCH_ONLY`

This is the second and final member of the current overnight-reversal research
family. It asks whether relative overnight dislocation across nine liquid U.S.
sector ETFs is more informative than the rejected single-index QQQ sign rule.

## Mechanism

Published research reports that buying assets with the lowest overnight returns
and selling those with the highest can produce intraday reversal, potentially
as compensation for supplying liquidity after temporary overnight imbalances.
The literature motivates the mechanism but does not validate this long-only,
sector-ETF, execution-delayed implementation.

At every common complete regular session:

1. Compute each sector's return from the prior 15:45 bar close to the current
   09:30 bar open.
2. Select the single minimum overnight-return sector, breaking exact ties by
   symbol.
3. Trade only if the selected return is negative.
4. Enter at the 09:45 bar open and exit at the 10:15 bar close.
5. Compare with the overnight winner, a fixed-hash random sector, the
   equal-weight sector basket, and SPY on exactly the same dates.

The frozen sector universe is `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`,
`XLV`, and `XLY`. The requested frequency is approximately one event per
session, or 3-5 candidates per week after incomplete sessions and non-negative
cross-sections are excluded.

## Guardrails

- Alpaca SIP 15-minute bars use split-and-dividend adjustment `all`.
- Primary costs are 2 basis points per side; stress costs are 5 per side.
- Development is 2016-2021, validation is 2022-2024, and dated confirmation is
  2025 through November 6, 2026.
- No universe, dispersion, gap, entry, exit, volatility, weekday, or regime
  sweep is allowed after the result.
- As the second adjacent overnight-reversal test, the primary Newey-West
  statistic must clear the locked family-wise threshold of 2.24.
- A historical pass remains research-only. It may open deterministic and LLM
  forward-shadow collection, but cannot activate paper or submit orders.
- An LLM arm, if earned, must use causal context, past-only memory, forward-
  calibrated probabilities, and immutable execution gates.

Primary mechanism reference: Chun Liu, Yang Liu, Tianyu Wang, Guofu Zhou, and
Yingzi Zhu, "Overnight-Intraday Reversal Everywhere" (2016, revised 2025),
SSRN 2730304, DOI `10.2139/ssrn.2730304`.
